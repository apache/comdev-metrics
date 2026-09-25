"""Mailing list discovery and metrics collector using the Pony Mail Foal API.

On each run:
1. Discovers all mailing lists via preferences.json
2. Filters to lists with traffic in the last 12 months ("recently active")
3. Collects volume/poster stats for active lists

Aggressive caching:
  - Past months are immutable. Once we have data for a completed month,
    we never re-fetch it.
  - Only the current month (which is still in progress) is refreshed on
    each run.
  - Cache stored in: <json_dir>/_cache/mailing_lists/<project>.json

API Reference: Pony Mail Foal uses POST with JSON body to /api/*.json.
See: incubator-ponymail-foal/docs/API.md
"""

from datetime import datetime
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import re
import httpx

from asfmetrics.collectors import cache as CACHE



PONYMAIL_API = "https://lists.apache.org/api/"

# Lists with no messages in this window are excluded from the dashboard
ACTIVITY_THRESHOLD = "12M"  # Full year — trends need context beyond a single quarter


_COLLECTOR_NAME = "mailing_lists"

# Max concurrent per-month numparts requests to the Pony Mail API. Kept
# deliberately low (4) to stay a polite consumer of a shared community API
# and avoid rate-limiting/blacklisting. Do not raise without checking ASF
# infra tolerance.
_MAX_CONCURRENCY = 4


def _widen_timespan_one_month(timespan: str) -> str:
    """Return a Pony Mail timespan one month wider than ``timespan``.

    e.g. "12M" -> "13M". Used so the fetched ``emails[]`` array reaches
    back far enough to cover the participant window's boundary month (which
    starts one month before the 12-month reporting cutoff). Without this the
    boundary month's messages exist in ``active_months`` (full history) but
    have no ``emails[]`` entries, so the client-side participant count for
    that month is 0 on low-volume lists. Falls back to the input unchanged
    if it is not the expected "<n>M" form.
    """
    m = re.fullmatch(r"(\d+)M", timespan.strip())
    if not m:
        return timespan
    return f"{int(m.group(1)) + 1}M"

# Above this many messages in a single month, the stats.json ``emails[]``
# array is capped by the server and does NOT contain every message — so a
# client-side distinct-sender count computed from it would undercount (and
# can miss whole months entirely). For any such month we instead make one
# lightweight per-month call and trust the server's ``numparts`` aggregate.
# Months at or below this count return a complete ``emails[]`` and are
# counted client-side with GitHub-identity normalization (cheaper: no extra
# call, and honours the (via GitHub) dedupe). Tune if the observed cap moves.
EMAILS_CAP_THRESHOLD = 500


# Matches Pony Mail's "(via GitHub)" relay wrapper, e.g.
#   "rbowen (via GitHub)" <git@apache.org>
# The underlying human is the leading token before the wrapper.
_VIA_GITHUB_RE = re.compile(r"\s*\(via GitHub\)\s*", re.IGNORECASE)


def _normalize_sender(raw_from: str) -> str | None:
    """Reduce a raw ``emails[].from`` value to a stable participant key.

    - Strips display-name quoting and the surrounding ``<addr>``.
    - Collapses ``"name (via GitHub)"`` relayed senders to the underlying
      username, so ``rbowen (via GitHub)`` and ``rbowen`` count as one
      participant (GitHub relays ARE real people acting through GitHub).
    - Prefers the email address when present (most stable identity);
      otherwise falls back to the cleaned display name.

    Returns a lowercased key, or None if nothing usable is found.

    Known limitation (accepted, Sep 2026): the same human who posts both
    via a GitHub relay (keyed on username) AND via direct email (keyed on
    address) counts as two distinct participants, because there is no
    reliable username->email mapping in the archive payload. Building such
    a map across 10k+ participants over 300+ projects is not feasible, so
    we accept modest over-counting. On GitHub-heavy lists the same person
    rarely does both in a month, so the effect is small.
    """
    if not raw_from:
        return None
    s = raw_from.strip()

    # Split display name from <address> if present.
    addr = None
    name = s
    m = re.match(r"^(.*?)<([^>]+)>\s*$", s)
    if m:
        name = m.group(1).strip()
        addr = m.group(2).strip().lower()

    name = name.strip().strip('"').strip()
    is_via_github = bool(_VIA_GITHUB_RE.search(name))
    name = _VIA_GITHUB_RE.sub("", name).strip().strip('"').strip()

    # For GitHub relays the address is a shared bot address (e.g.
    # git@apache.org / *@github.com), so the username in the display name
    # is the real identity — key on that.
    if is_via_github and name:
        return name.lower()

    if addr:
        return addr
    return name.lower() or None


def _participants_by_month(emails: list) -> dict[str, int]:
    """Count distinct normalized senders per calendar month.

    Args:
        emails: The ``emails[]`` array from a full (non-quick) stats.json
            response. Each entry has ``from`` and ``epoch``.

    Returns:
        Dict of {YYYY-MM: distinct_sender_count}.
    """
    buckets: dict[str, set] = {}
    for e in emails or []:
        epoch = e.get("epoch")
        if epoch is None:
            continue
        dt = datetime.utcfromtimestamp(epoch)
        month_key = f"{dt.year}-{dt.month:02d}"
        key = _normalize_sender(e.get("from", ""))
        if key is None:
            continue
        buckets.setdefault(month_key, set()).add(key)
    return {m: len(s) for m, s in buckets.items()}


# Module-level counter so the CLI can report how many per-month API calls
# the hybrid strategy actually made on a run (timing/observability).
_MONTH_CALLS = 0
# Guards _MONTH_CALLS since per-month calls now run on a thread pool.
_MONTH_CALLS_LOCK = threading.Lock()


def reset_call_counter() -> None:
    """Reset the per-month API call counter (call once at run start)."""
    global _MONTH_CALLS
    with _MONTH_CALLS_LOCK:
        _MONTH_CALLS = 0


def get_call_counter() -> int:
    """Return the number of per-month numparts calls made so far."""
    return _MONTH_CALLS


def _fetch_month_numparts(
    list_name: str,
    domain: str,
    month_key: str,
    base_url: str = PONYMAIL_API,
) -> int | None:
    """Fetch the server-side distinct-participant count for ONE month.

    Makes a single ``stats.json`` call scoped to ``month_key`` (YYYY-MM)
    and returns its ``numparts``. Used for high-volume months where the
    ``emails[]`` array is capped and a client-side count is unreliable.

    The response for a single month is small regardless of the list's
    overall volume, so this is a lightweight call.

    Returns the month's numparts, or None on failure.
    """
    global _MONTH_CALLS
    url = f"{base_url}stats.json"
    payload = {"list": list_name, "domain": domain, "d": month_key}
    try:
        with _MONTH_CALLS_LOCK:
            _MONTH_CALLS += 1
        resp = httpx.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    return data.get("numparts", 0)


def _participants_by_month_hybrid(
    list_name: str,
    domain: str,
    active_months: dict[str, int],
    emails: list,
    base_url: str = PONYMAIL_API,
    only_months: set[str] | None = None,
) -> dict[str, int]:
    """Compute distinct participants per month using the hybrid strategy.

    - For months whose message count is at or below EMAILS_CAP_THRESHOLD,
      the ``emails[]`` array is complete: count normalized distinct senders
      client-side (cheap, honours (via GitHub) dedupe).
    - For high-volume months (count > threshold), ``emails[]`` is capped,
      so make one per-month ``numparts`` call each and trust the server.

    Args:
        active_months: {YYYY-MM: message_count} for this list (the window).
        emails: the ``emails[]`` array from the same response.
        only_months: if given, restrict computation to these month keys
            (used by incremental refresh to only touch the current window).

    Returns:
        {YYYY-MM: distinct_participant_count}.
    """
    # Base client-side counts from the (possibly capped) emails[] array.
    client_counts = _participants_by_month(emails)

    result: dict[str, int] = {}
    api_months: list[str] = []
    for month_key, msg_count in active_months.items():
        if only_months is not None and month_key not in only_months:
            continue
        if msg_count > EMAILS_CAP_THRESHOLD:
            # emails[] unreliable for this month → needs an authoritative
            # per-month call (collected below and run concurrently).
            api_months.append(month_key)
        else:
            # Small month → emails[] is complete; client-side count is exact.
            result[month_key] = client_counts.get(month_key, 0)

    # Run the per-month numparts calls concurrently, but bounded to
    # _MAX_CONCURRENCY to stay polite to the shared Pony Mail API. Each
    # call falls back to the client-side count if it fails.
    if api_months:
        def _one(mk: str) -> tuple[str, int]:
            np = _fetch_month_numparts(list_name, domain, mk, base_url)
            return mk, (np if np is not None else client_counts.get(mk, 0))

        workers = min(_MAX_CONCURRENCY, len(api_months))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for mk, count in pool.map(_one, api_months):
                result[mk] = count

    return result



def invalidate_cache(config: dict) -> None:
    """Remove all mailing list cache files."""
    CACHE.invalidate(config, _COLLECTOR_NAME)






def discover_lists(base_url: str = PONYMAIL_API) -> dict:
    """Discover all mailing lists from the Pony Mail preferences endpoint.

    Returns:
        Dict of {domain: {list_name: count, ...}, ...}
        e.g. {"httpd.apache.org": {"dev": 1523, "users": 890}}
    """
    url = f"{base_url}preferences.json"
    try:
        resp = httpx.post(url, json={}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        print(f"    warning: failed to discover lists: {e}")
        return {}

    return data.get("lists", {})


def collect_list_stats(
    list_name: str,
    domain: str,
    base_url: str = PONYMAIL_API,
    timespan: str = ACTIVITY_THRESHOLD,
    quick: bool = False,
) -> dict | None:
    """Fetch stats for a single mailing list.

    Uses the Foal stats.json endpoint (POST with JSON body).

    Args:
        list_name: List name prefix (e.g. "dev").
        domain: List domain (e.g. "httpd.apache.org").
        base_url: Pony Mail API base URL.
        timespan: Date filter in Pony Mail format (e.g. "6M", "3M").
        quick: If True, return summary stats only. Must be False (the
            default) to receive the per-message ``emails[]`` array that
            participant-per-month counting relies on. quick=True sets
            numparts=0 and omits emails[] entirely.

    Returns:
        Stats dict with hits, numparts, no_threads, etc. or None on failure.
    """
    url = f"{base_url}stats.json"
    payload = {
        "list": list_name,
        "domain": domain,
        "d": f"lte={timespan}",
    }
    if quick:
        payload["quick"] = True

    try:
        resp = httpx.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None

    # No messages in this window
    if data.get("hits", 0) == 0:
        return None

    return data


def _fetch_current_month_stats(
    list_name: str,
    domain: str,
    base_url: str = PONYMAIL_API,
) -> dict | None:
    """Fetch stats for the current + previous month (2M window).

    Used for incremental cache updates. We use 2M (not 1M) because if
    the last run was late in the previous month, the previous month's
    final count may have increased since then. Two months guarantees
    we pick up the tail end of the previous month.
    """
    return collect_list_stats(list_name, domain, base_url, timespan="2M", quick=False)


def collect_mailing_list_stats(
    project: str, config: dict,
    mail_domain_map: dict[str, str] | None = None,
) -> dict | None:
    """Collect mailing list statistics for a single project, with caching.

    Caching behavior:
      - If cache exists and was fetched this month: return cached data (no API calls).
      - If cache exists but from a previous month: only refresh current month data.
      - If no cache: full fetch, then cache the result.

    Past months are immutable — once a month ends, its data never changes.
    Only the current (in-progress) month needs refreshing.

    Args:
        project: ASF project name (e.g. 'kafka', 'comdev').
        config: Full config dict.
        mail_domain_map: Optional mapping of project id → mailing list
            domain (e.g. ``{'comdev': 'community.apache.org'}``).

    Returns:
        Dict with per-list stats, or None if no active lists found.
    """
    base_url = (
        config.get("data_sources", {})
        .get("mailing_lists", {})
        .get("base_url", PONYMAIL_API)
    )
    timespan = (
        config.get("data_sources", {})
        .get("mailing_lists", {})
        .get("activity_threshold", ACTIVITY_THRESHOLD)
    )

    # Derive mailing list domain from Whimsy committee-info.json data.
    # Falls back to the standard {project}.apache.org pattern.
    if mail_domain_map:
        domain = mail_domain_map.get(project, f"{project}.apache.org")
    else:
        domain = f"{project}.apache.org"

    # Check cache
    cache = CACHE.load_cache(project, config, _COLLECTOR_NAME)
    # current_month = CACHE.current_month_str()

    if cache and CACHE.cache_is_current(cache):
        # Cache is fresh — return directly without any API calls
        return _build_result_from_cache(project, domain, timespan, cache)

    if cache and cache.get("lists"):
        # Cache exists but stale (from a previous month).
        # Past months are immutable — only refresh the current month.
        updated = False
        for list_id, list_data in cache.get("lists", {}).items():
            list_name = list_data.get("list_name", list_id.split("@")[0])
            stats = _fetch_current_month_stats(list_name, domain, base_url)
            if stats:
                months = stats.get("active_months", {})
                # Update current + previous month in the cached months
                # (2M window covers both; previous month may have grown since last fetch)
                cached_months = list_data.get("active_months", {})
                for month_key, count in months.items():
                    # Overwrite any month returned by the 2M window
                    # (current month + previous month)
                    cached_months[month_key] = count
                list_data["active_months"] = cached_months
                # Recompute participants for the refreshed months and merge.
                # Past months are immutable; only the 2M window is overwritten.
                # Use the hybrid strategy scoped to just the months this 2M
                # window returned, so a high-volume current month still gets
                # an authoritative per-month numparts call.
                refreshed = set(months.keys())
                fresh_parts = _participants_by_month_hybrid(
                    list_name, domain, cached_months,
                    stats.get("emails", []), base_url,
                    only_months=refreshed,
                )
                cached_parts = list_data.get("participants_by_month", {})
                for month_key, pcount in fresh_parts.items():
                    cached_parts[month_key] = pcount
                list_data["participants_by_month"] = cached_parts
                # Update totals from the full month range
                list_data["messages"] = sum(
                    v for k, v in cached_months.items()
                    if k >= CACHE.twelve_months_ago_str()
                )
                list_data["participants"] = stats.get("numparts", list_data.get("participants", 0))
                list_data["threads"] = stats.get("no_threads", list_data.get("threads", 0))
                updated = True

        if updated:
            cache["_fetched_at"] = datetime.now().strftime("%Y-%m-%d")
            CACHE.save_cache(project, cache, config, _COLLECTOR_NAME)

        return _build_result_from_cache(project, domain, timespan, cache)

    # No cache — full fetch
    # Discover all lists for this domain from preferences
    all_domain_lists = discover_lists(base_url)
    project_lists = list(all_domain_lists.get(domain, {}).keys())

    # If we can't discover, fall back to conventional names
    if not project_lists:
        project_lists = ["dev", "user", "users", "general"]

    active_lists = []
    cache_lists = {}

    for list_name in project_lists:
        # Fetch one month wider than the reporting window so the emails[]
        # array covers the participant boundary month (see
        # _widen_timespan_one_month). active_months is full history either
        # way; only the emails[] coverage matters here.
        fetch_span = _widen_timespan_one_month(timespan)
        stats = collect_list_stats(list_name, domain, base_url, fetch_span)
        if stats:
            list_id = f"{list_name}@{domain}"
            active_months = stats.get("active_months", {})

            # Only compute participants for the reporting window; older
            # months are never shown and must not trigger per-month calls.
            # Use the participant-window start (one month earlier than the
            # 12-month cutoff) so the chart's leftmost bar always has a
            # participant value — see participant_window_start_str().
            cutoff = CACHE.participant_window_start_str()
            window_months = {
                k: v for k, v in active_months.items() if k >= cutoff
            }
            pbm = _participants_by_month_hybrid(
                list_name, domain, window_months,
                stats.get("emails", []), base_url,
            )

            list_entry = {
                "list_name": list_name,
                "list_id": list_id,
                "messages": stats.get("hits", 0),
                "participants": stats.get("numparts", 0),
                "threads": stats.get("no_threads", 0),
                "active_months": active_months,
                "participants_by_month": pbm,
            }
            active_lists.append(list_entry)
            cache_lists[list_id] = list_entry

    if not active_lists:
        return None

    # Save cache
    cache_data = {
        "_fetched_at": datetime.now().strftime("%Y-%m-%d"),
        "_project": project,
        "_domain": domain,
        "lists": cache_lists,
    }
    CACHE.save_cache(project, cache_data, config, _COLLECTOR_NAME)

    return {
        "project": project,
        "domain": domain,
        "timespan": timespan,
        "active_lists": active_lists,
    }



def _build_result_from_cache(
    project: str,
    domain: str,
    timespan: str,
    cache: dict,
) -> dict | None:
    """Reconstruct the API result format from cached data.

    Filters to the 12-month window for the output.
    """
    cutoff = CACHE.twelve_months_ago_str()
    active_lists = []

    for list_id, list_data in cache.get("lists", {}).items():
        all_months = list_data.get("active_months", {})
        # Filter to 12-month window
        recent_months = {
            k: v for k, v in all_months.items() if k >= cutoff
        }
        if not recent_months:
            continue

        all_parts = list_data.get("participants_by_month", {})
        # Participants use a one-month-wider window than messages so the
        # chart's leftmost bar always has a value (see
        # participant_window_start_str()).
        parts_cutoff = CACHE.participant_window_start_str()
        recent_parts = {
            k: v for k, v in all_parts.items() if k >= parts_cutoff
        }

        active_lists.append({
            "list_name": list_data.get("list_name", list_id.split("@")[0]),
            "list_id": list_id,
            "messages": sum(recent_months.values()),
            "participants": list_data.get("participants", 0),
            "participants_by_month": recent_parts,
            # Peak monthly participants across the window — a defensible
            # single-number summary. (A true 12-month distinct union isn't
            # derivable from per-month counts; numparts in "participants"
            # is the API's window-wide distinct total.)
            "participants_peak_month": max(recent_parts.values(), default=0),
            "threads": list_data.get("threads", 0),
            "active_months": recent_months,
        })

    if not active_lists:
        return None

    return {
        "project": project,
        "domain": domain,
        "timespan": timespan,
        "active_lists": active_lists,
    }


def discover_all_active_projects(config: dict) -> list[str]:
    """Discover all projects that have at least one recently-active list.

    Queries the preferences.json endpoint to get all known lists,
    then returns projects whose domain has any list with recorded messages.

    Args:
        config: Full config dict.

    Returns:
        Sorted list of project names with mailing list activity.
    """
    base_url = (
        config.get("data_sources", {})
        .get("mailing_lists", {})
        .get("base_url", PONYMAIL_API)
    )

    print("    discovering mailing lists from Pony Mail...")
    all_lists = discover_lists(base_url)
    print(f"    found {len(all_lists)} domains")

    # Domain -> project name mapping
    # Most are simply project.apache.org, but some are different
    reverse_domain = {
        "community.apache.org": "comdev",
        "infra.apache.org": "infrastructure",
        "whimsical.apache.org": "whimsy",
    }

    active_projects = set()
    for domain, lists in all_lists.items():
        if not domain.endswith(".apache.org"):
            continue
        # Check if any list in this domain has messages
        if any(count > 0 for count in lists.values()):
            project = reverse_domain.get(domain, domain.replace(".apache.org", ""))
            active_projects.add(project)

    print(f"    {len(active_projects)} projects with mailing list activity")
    return sorted(active_projects)

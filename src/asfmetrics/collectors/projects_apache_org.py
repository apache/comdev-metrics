"""Collector that fetches pre-built JSON from projects.apache.org.

This is the pragmatic "get started quick" data source. These JSON files
are generated daily by comdev-projects cronjobs from authoritative sources
(Whimsy committee-info, LDAP, the Incubator, the ASF release catalog) and
published publicly.

Release data is the exception: it is read directly from the ASF release
catalog (RELEASE_CATALOG_URL), which Tooling has designated the
authoritative source, rather than via projects.apache.org.

Later we can swap individual data points for direct Whimsy/LDAP/GitHub
queries, but this gets us a full dataset on day one with zero auth.

Public JSON base: https://projects.apache.org/json/foundation/
"""

import json
import re
from datetime import datetime
from pathlib import Path

import httpx

from asfmetrics.config import get_cache_dir, get_state_dir, NEW_COMMITTERS_FILE


BASE_URL = "https://projects.apache.org/json/foundation/"

# Files we fetch and cache locally
# Not all are needed at run-time: see the comments below
FOUNDATION_FILES = {
    "committees.json": "PMC roster, chairs, charters, established dates", # needed by website
    "committees-retired.json": "Retired committees",
    "people.json": "Committer → project membership mapping",
    "podlings.json": "Current podlings + status",
    "repositories.json": "Git/SVN repository listing",
    "projects.json": "Project metadata (from the ASF release catalog)",
}

# Authoritative release data (Apache Trusted Releases / Tooling)
RELEASE_CATALOG_URL = "https://release-catalog.apache.org/project_releases.json"
# Podling releases are published separately, keyed by bare podling id
PODLING_CATALOG_URL = "https://release-catalog.apache.org/podling_releases.json"
RELEASES_FILE = "releases.json"   # written to the cache dir; read by the website

# Whimsy public JSON for committer creation dates
WHIMSY_LDAP_PEOPLE = "https://whimsy.apache.org/public/public_ldap_people.json"
# Also fetch committee-info.json from Whimsy for PMC dates (more authoritative)
WHIMSY_COMMITTEE_INFO = "https://whimsy.apache.org/public/committee-info.json"


def fetch_foundation_json(
    filename: str, base_url: str = BASE_URL, timeout: int = 30
) -> dict | list | None:
    """Fetch a single foundation JSON file from projects.apache.org.

    Args:
        filename: JSON filename (e.g. 'committees.json').
        base_url: Base URL for the JSON files.
        timeout: Request timeout in seconds.

    Returns:
        Parsed JSON (dict or list), or None on failure.
    """
    url = f"{base_url}{filename}"
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError) as e:
        print(f"    warning: failed to fetch {filename}: {e}")
        return None


def fetch_all_foundation_data(config: dict) -> dict:
    """Fetch all foundation JSON files and cache locally.

    Args:
        config: Full asfmetrics config dict.

    Returns:
        Dict keyed by filename (without .json), value is parsed data.
    """
    base_url = (
        config.get("data_sources", {})
        .get("projects_apache_org", {})
        .get("base_url", BASE_URL)
    )
    cache_dir = get_cache_dir(config)

    data = {}
    for filename, description in FOUNDATION_FILES.items():
        key = filename.replace(".json", "").replace("-", "_")
        print(f"    fetching {filename} ({description})...")
        content = fetch_foundation_json(filename, base_url)
        if content is not None:
            data[key] = content
            # Cache locally for offline/debugging use
            cache_path = cache_dir / filename
            with open(cache_path, "w", encoding='utf-8') as f:
                json.dump(content, f, indent=2)

    print(f"    fetched {len(data)}/{len(FOUNDATION_FILES)} files successfully")
    return data


def fetch_release_catalog(timeout: int = 120, url: str = RELEASE_CATALOG_URL) -> dict | None:
    """Fetch the ASF release catalog.

    Returns:
        Dict keyed by catalog project key, each with 'pmc', 'name' and a
        'release' list of {'name', 'revision', 'created'}; or None on failure.
    """
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        print(f"    warning: failed to fetch release catalog: {e}")
        return None
    if not isinstance(data, dict):
        print("    warning: release catalog has unexpected shape")
        return None
    return data


def build_releases_by_project(catalog: dict, podling_ids=()) -> dict[str, dict[str, str]]:
    """Group catalog releases by the ids the dashboard uses.

    The dashboard identifies a TLP by its committee id and a podling by its
    bare podling name (as in podlings.json). The catalog's 'pmc' field
    already follows that convention, but some podling entries may carry
    'incubator' or an 'incubator-' prefix, so both are normalised here.

    Returns:
        { project_id: { "<name> <version>": "YYYY-MM-DD" } }; the same shape
        as the old projects.apache.org releases.json, so the pages are
        unchanged.
    """
    podlings = set(podling_ids)
    out: dict[str, dict[str, str]] = {}
    for key, entry in catalog.items():
        if not isinstance(entry, dict):
            continue
        pmc = (entry.get("pmc") or key.split("-")[0]).strip()
        if pmc == "incubator" or pmc.startswith("incubator-"):
            bare = re.sub(r"^incubator-", "", key if pmc == "incubator" else pmc)
            # match the longest podling id that the key starts with
            pmc = next((p for p in sorted(podlings, key=len, reverse=True)
                        if bare == p or bare.startswith(p + "-")), bare)
        name = re.sub(r"^Apache\s+", "", entry.get("name") or key)
        for rel in entry.get("release") or []:
            if not isinstance(rel, dict):
                continue
            date = (rel.get("created") or "")[:10]
            if not re.match(r"\d{4}-\d{2}-\d{2}$", date):
                continue
            version = rel.get("revision") or rel.get("version") or ""
            relname = re.sub(r"^Apache\s+", "", rel.get("name") or name)
            label = f"{relname} {version}".strip()
            out.setdefault(pmc, {})[label] = date
    return out


def collect_releases(data: dict, config: dict) -> dict:
    """Build and cache releases.json from the release catalog.

    Falls back to the previously cached file if the catalog can't be fetched.
    """
    cache_path = get_cache_dir(config) / RELEASES_FILE
    print("    fetching release catalog (authoritative release data)...")
    catalog = fetch_release_catalog()
    if catalog is None:
        if cache_path.exists():
            print("    using cached releases.json")
            with open(cache_path, encoding="utf-8") as f:
                return json.load(f)
        return {}
    podlings = data.get("podlings") or {}
    releases = build_releases_by_project(catalog, podlings.keys() if isinstance(podlings, dict) else ())
    # Podlings: separate file, already keyed by bare podling id
    podling_catalog = fetch_release_catalog(url=PODLING_CATALOG_URL) or {}
    for pid, rels in build_releases_by_project(podling_catalog).items():
        releases.setdefault(pid, {}).update(rels)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(releases, f, indent=2, sort_keys=True)
    n = sum(len(v) for v in releases.values())
    print(f"    {n} releases for {len(releases)} projects from the release catalog")
    return releases


def build_mail_domain_map(_config: dict) -> dict[str, str]:
    """Build a committee-id → mailing list domain map from Whimsy.

    Fetches committee-info.json and extracts the 'mail_list' field,
    which gives the correct mailing list domain prefix for each
    committee.  For most projects the domain is simply
    ``{project}.apache.org``, but some differ (e.g. comdev →
    community.apache.org, infrastructure → infra.apache.org).

    Returns:
        Dict mapping committee id to full domain, e.g.
        ``{'comdev': 'community.apache.org', ...}``.
        Only entries where the domain differs from the default
        ``{id}.apache.org`` pattern are included.
    """
    print("    fetching Whimsy committee-info.json for mail domains...")
    try:
        resp = httpx.get(WHIMSY_COMMITTEE_INFO, timeout=60, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        print(f"    warning: failed to fetch committee-info.json: {e}")
        return {}

    domain_map = {}
    for cid, info in data.get("committees", {}).items():
        mail_list = info.get("mail_list", "")
        if mail_list and mail_list != cid:
            domain_map[cid] = f"{mail_list}.apache.org"

    print(f"    mail domain overrides from Whimsy: {len(domain_map)} entries")
    return domain_map


def extract_active_projects(data: dict) -> list[str]:
    """Get sorted list of active project names — TLPs + current podlings.

    Args:
        data: Dict from fetch_all_foundation_data().

    Returns:
        Sorted list of project IDs (e.g. ['accumulo', 'airflow', ..., 'ponymail', ...]).
    """
    projects = set()

    # TLPs from committees.json
    committees = data.get("committees", [])
    if isinstance(committees, list):
        for c in committees:
            if "id" in c:
                projects.add(c["id"])

    # Current podlings from podlings.json
    podlings = data.get("podlings", {})
    if isinstance(podlings, dict):
        for name, info in podlings.items():
            # Only include active podlings (status = "current")
            status = info.get("status", "").lower() if isinstance(info, dict) else ""
            if status == "current":
                projects.add(name.lower())
    elif isinstance(podlings, list):
        for p in podlings:
            if isinstance(p, dict) and p.get("status", "").lower() == "current":
                projects.add(p.get("name", p.get("id", "")).lower())

    return sorted(projects)


def detect_roster_changes(current_data: dict, state_dir: Path) -> dict:
    """Detect new committers/PMC members by comparing roster dates.

    Compares current committees.json roster entries against the previous
    cached version. Any roster entry with a 'date' field newer than the
    last run is flagged as a new addition.

    Args:
        current_data: Dict from fetch_all_foundation_data().
        state_dir: Path to directory containing previous state.

    Returns:
        Dict with: new_committers (list), new_pmcs (list of graduated),
        retired (list).
    """
    changes = {
        "new_roster_entries": [],  # {project, person, date}
        "newly_retired": [],
    }

    state_path = state_dir / "_committees_previous.json"
    committees = current_data.get("committees", [])

    if not isinstance(committees, list):
        return changes

    # Build current roster snapshot
    current_roster = {}
    for pmc in committees:
        project_id = pmc.get("id", "")
        roster = pmc.get("roster", {})
        for uid, info in roster.items():
            current_roster[f"{project_id}/{uid}"] = info.get("date", "")

    # Compare against previous
    if state_path.exists():
        with open(state_path, encoding='utf-8') as f:
            previous_roster = json.load(f)

        new_entries = set(current_roster.keys()) - set(previous_roster.keys())
        for key in sorted(new_entries):
            project_id, uid = key.split("/", 1)
            changes["new_roster_entries"].append({
                "project": project_id,
                "person": uid,
                "date": current_roster[key],
            })

    # Detect newly retired (compare retired lists)
    retired = current_data.get("committees_retired", [])
    retired_state_path = state_dir / "_retired_previous.json"
    if isinstance(retired, list) and retired_state_path.exists():
        with open(retired_state_path, encoding='utf-8') as f:
            prev_retired = json.load(f)
        prev_ids = {r.get("id") for r in prev_retired if isinstance(r, dict)}
        curr_ids = {r.get("id") for r in retired if isinstance(r, dict)}
        changes["newly_retired"] = sorted(curr_ids - prev_ids)

    # Save current state for next run
    with open(state_path, "w", encoding='utf-8') as f:
        json.dump(current_roster, f)
    if isinstance(retired, list):
        with open(retired_state_path, "w", encoding='utf-8') as f:
            json.dump(retired, f)

    return changes


def collect_new_committers(data: dict, _config: dict) -> dict:
    """Detect new committers using Whimsy LDAP createTimestamp.

    Fetches public_ldap_people.json from Whimsy and cross-references
    with people.json to find committers created in the last 12 months,
    grouped by project.

    Returns:
        Dict with: by_project (project -> list of {name, id, date}),
                   total (int), by_month (YYYY-MM -> count)
    """
    print("    fetching Whimsy LDAP data for new committer dates...")

    try:
        resp = httpx.get(WHIMSY_LDAP_PEOPLE, timeout=60, follow_redirects=True)
        resp.raise_for_status()
        ldap_data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        print(f"    warning: failed to fetch Whimsy LDAP data: {e}")
        return {"by_project": {}, "total": 0, "by_month": {}}

    people_data = data.get("people", {})
    ldap_people = ldap_data.get("people", ldap_data)

    # 12-month cutoff
    now = datetime.now()
    cutoff = now.replace(year=now.year - 1)

    new_committers_by_project = {}
    by_month = {}
    total = 0

    for person_id, person_info in people_data.items():
        if person_id not in ldap_people:
            continue

        ldap_entry = ldap_people[person_id]
        create_ts = ldap_entry.get("createTimestamp", "")
        if not create_ts:
            continue

        try:
            created = datetime.strptime(create_ts, "%Y%m%d%H%M%SZ")
        except (ValueError, TypeError):
            continue

        if created < cutoff:
            continue

        # This person was created in the last 12 months — they're a new committer
        month_key = created.strftime("%Y-%m")
        by_month[month_key] = by_month.get(month_key, 0) + 1
        total += 1

        for group in person_info.get("groups", []):
            # Skip meta-groups
            if group.endswith("-pmc") or group in ("apldap", "incubator", "member"):
                continue
            if group not in new_committers_by_project:
                new_committers_by_project[group] = []
            new_committers_by_project[group].append({
                "name": person_info.get("name", person_id),
                "id": person_id,
                "date": created.strftime("%Y-%m-%d"),
            })

    print(f"    new committers (12mo): {total} across {len(new_committers_by_project)} projects")

    return {
        "by_project": new_committers_by_project,
        "total": total,
        "by_month": by_month,
    }


def collect_projects_apache_org(config: dict) -> dict:
    """Main entry point: fetch all data, detect changes, return summary.

    Args:
        config: Full asfmetrics config dict.

    Returns:
        Dict with foundation data, active projects, and detected changes.
    """
    print("  collecting from projects.apache.org...")
    data = fetch_all_foundation_data(config)
    data["releases"] = collect_releases(data, config)

    state_dir = get_state_dir(config)

    active_projects = extract_active_projects(data)
    roster_changes = detect_roster_changes(data, state_dir)

    # Build mail domain map from Whimsy committee-info.json
    mail_domain_map = build_mail_domain_map(config)

    # Detect new committers from Whimsy LDAP
    new_committers = collect_new_committers(data, config)

    # Save new committers data for the frontend
    cache_dir = get_cache_dir(config)
    with open(cache_dir / NEW_COMMITTERS_FILE, "w", encoding='utf-8') as f:
        json.dump(new_committers, f, indent=2)

    print(f"    {len(active_projects)} active projects")
    if roster_changes["new_roster_entries"]:
        print(f"    {len(roster_changes['new_roster_entries'])} new roster entries since last run")
    if roster_changes["newly_retired"]:
        print(f"    {len(roster_changes['newly_retired'])} newly retired projects")

    return {
        "active_projects": active_projects,
        "roster_changes": roster_changes,
        "new_committers": new_committers,
        "mail_domain_map": mail_domain_map,
        "data": data,
    }

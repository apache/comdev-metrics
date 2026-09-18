"""Shared caching utilities for collectors.

Both the mailing list and git activity collectors use the same
month-granularity caching pattern: past months are immutable, only the
current month is refreshed, and a same-day check avoids redundant API
calls during development.

Each collector stores its cache in a subdirectory under _cache/
(e.g. _cache/mailing_lists/, _cache/git/).
"""

import json
from datetime import datetime
from pathlib import Path

from asfmetrics.config import get_cache_dir


# --- Date helpers ---

def current_month_str() -> str:
    """Return current month as YYYY-MM."""
    now = datetime.now()
    return f"{now.year}-{now.month:02d}"


def twelve_months_ago() -> datetime:
    """Return datetime 12 months before now."""
    now = datetime.now()
    return now.replace(year=now.year - 1)


def twelve_months_ago_str() -> str:
    """Return YYYY-MM string for 12 months ago."""
    dt = twelve_months_ago()
    return f"{dt.year}-{dt.month:02d}"


# --- Cache directory ---

def collector_cache_dir(config: dict, collector_name: str) -> Path:
    """Return the cache directory for a specific collector.

    Args:
        config: Full config dict.
        collector_name: Subdirectory name (e.g. 'mailing_lists', 'git').

    Returns:
        Path to the cache directory (created if necessary).
    """
    cache_dir = get_cache_dir(config) / collector_name
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


# --- Load / save / check ---

def load_cache(project: str, config: dict, collector_name: str) -> dict | None:
    """Load cached data for a project.

    Returns:
        Cached dict, or None if no cache exists or it's corrupt.
    """
    cache_path = collector_cache_dir(config, collector_name) / f"{project}.json"
    if not cache_path.exists():
        return None
    try:
        with open(cache_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_cache(project: str, cache_data: dict, config: dict, collector_name: str) -> None:
    """Save collected data to the project cache."""
    cache_path = collector_cache_dir(config, collector_name) / f"{project}.json"
    with open(cache_path, "w") as f:
        json.dump(cache_data, f, indent=2)


def cache_is_current(cache: dict) -> bool:
    """Check if cache was fetched today.

    Same-day re-runs are skipped to save API calls during development.
    Next-day or later runs always refresh current-month data.
    """
    fetched_at = cache.get("_fetched_at", "")
    today = datetime.now().strftime("%Y-%m-%d")
    return fetched_at == today


def invalidate(config: dict, collector_name: str) -> None:
    """Remove all cache files for a collector (for --force-refresh)."""
    cache_dir = collector_cache_dir(config, collector_name)
    if cache_dir.exists():
        for f in cache_dir.glob("*.json"):
            f.unlink()
        print(f"    cleared {cache_dir}")

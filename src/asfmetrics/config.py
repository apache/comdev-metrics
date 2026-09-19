"""Configuration loading for asfmetrics.

Lookup order:
1. ./config.yml (project-local)
2. ~/.asfmetrics/config.yml (user-level)
3. /etc/asfmetrics/config.yml (system-level)
"""

from pathlib import Path

import yaml


# --- Shared path constants ---
DEFAULT_JSON_DIR = "./site/data/"
CACHE_SUBDIR = "_cache"
STATE_SUBDIR = "_state"
PROJECT_MAP_FILE = "_project_map.json"
MAILING_SUMMARY_FILE = "mailing_summary.json"
NEW_COMMITTERS_FILE = "new_committers.json"
FOUNDATION_FILE = "_foundation"


CONFIG_SEARCH_PATHS = [
    Path("./config.yml"),
    Path.home() / ".asfmetrics" / "config.yml",
    Path("/etc/asfmetrics/config.yml"),
]


def find_config() -> Path | None:
    """Find the first config file that exists."""
    for path in CONFIG_SEARCH_PATHS:
        if path.exists():
            return path
    return None


def load_config(path: Path | None = None) -> dict:
    """Load configuration from YAML file.

    Args:
        path: Explicit path to config. If None, searches default locations.

    Returns:
        Parsed config dict.

    Raises:
        FileNotFoundError: If no config file is found.
    """
    if path is None:
        path = find_config()
    if path is None:
        raise FileNotFoundError(
            "No config.yml found. Searched:\n"
            + "\n".join(f"  - {p}" for p in CONFIG_SEARCH_PATHS)
            + "\nCopy config.example.yml to config.yml to get started."
        )
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_json_dir(config: dict) -> Path:
    """Resolve the JSON output directory from config.

    Returns:
        Path to the output directory (created if necessary).
    """
    d = Path(config.get("output", {}).get("json_dir", DEFAULT_JSON_DIR))
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_cache_dir(config: dict) -> Path:
    """Resolve the cache subdirectory under the JSON output dir."""
    d = get_json_dir(config) / CACHE_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_state_dir(config: dict) -> Path:
    """Resolve the state subdirectory under the JSON output dir."""
    d = get_json_dir(config) / STATE_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d

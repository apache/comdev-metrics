"""Tests for collectors/projects_apache_org.py — foundation data helpers."""

from datetime import UTC, datetime

from asfmetrics.collectors import projects_apache_org as PAO
from asfmetrics.collectors.projects_apache_org import extract_active_projects


# --- extract_active_projects ---

def test_extract_from_committees_list():
    data = {
        "committees": [
            {"id": "kafka"},
            {"id": "airflow"},
            {"id": "comdev"},
        ],
        "podlings": {},
    }
    result = extract_active_projects(data)
    assert result == ["airflow", "comdev", "kafka"]  # sorted


def test_extract_includes_current_podlings():
    data = {
        "committees": [{"id": "kafka"}],
        "podlings": {
            "Pekko": {"status": "current"},
            "OldThing": {"status": "retired"},
        },
    }
    result = extract_active_projects(data)
    assert "pekko" in result
    assert "oldthing" not in result
    assert "kafka" in result


def test_extract_empty_data():
    data = {"committees": [], "podlings": {}}
    result = extract_active_projects(data)
    assert result == []


def test_extract_deduplicates():
    """If a project appears in both committees and podlings, no duplicates."""
    data = {
        "committees": [{"id": "spark"}],
        "podlings": {"Spark": {"status": "current"}},
    }
    result = extract_active_projects(data)
    assert result.count("spark") == 1


# --- collect_new_committers (issue #4: podlings must not appear) ---

class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _recent_ts():
    return datetime.now(UTC).strftime("%Y%m%d%H%M%SZ")


def test_new_committers_excludes_podlings(monkeypatch):
    ldap = {"people": {
        "alice": {"createTimestamp": _recent_ts()},
        "bob": {"createTimestamp": _recent_ts()},
    }}
    monkeypatch.setattr(PAO.httpx, "get", lambda *a, **k: _Resp(ldap))
    data = {
        "committees": [{"id": "kafka"}],
        "people": {
            "alice": {"name": "Alice", "groups": ["kafka", "kafka-pmc", "member"]},
            "bob": {"name": "Bob", "groups": ["maka", "incubator"]},  # podling only
        },
    }
    result = PAO.collect_new_committers(data, {})
    assert set(result["by_project"]) == {"kafka"}
    assert [p["id"] for p in result["by_project"]["kafka"]] == ["alice"]
    assert result["total"] == 1


def test_new_committers_ignores_old_accounts(monkeypatch):
    ldap = {"people": {"carol": {"createTimestamp": "20100101000000Z"}}}
    monkeypatch.setattr(PAO.httpx, "get", lambda *a, **k: _Resp(ldap))
    data = {
        "committees": [{"id": "kafka"}],
        "people": {"carol": {"name": "Carol", "groups": ["kafka"]}},
    }
    result = PAO.collect_new_committers(data, {})
    assert result["total"] == 0
    assert result["by_project"] == {}

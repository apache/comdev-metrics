"""Tests for collectors/projects_apache_org.py — foundation data helpers."""

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

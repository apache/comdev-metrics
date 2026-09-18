"""Tests for collectors/github_repos.py — repo classification."""

from asfmetrics.collectors.github_repos import classify_repo, build_project_map


# --- classify_repo ---

def test_classify_simple_repo():
    result = classify_repo("kafka")
    assert result == {"project": "kafka", "sub_repo": None, "incubating": False}


def test_classify_sub_repo():
    result = classify_repo("kafka-site")
    assert result == {"project": "kafka", "sub_repo": "site", "incubating": False}


def test_classify_incubator_repo():
    result = classify_repo("incubator-ponymail")
    assert result == {"project": "ponymail", "sub_repo": None, "incubating": True}


def test_classify_incubator_sub_repo():
    result = classify_repo("incubator-ponymail-foal")
    assert result == {"project": "ponymail", "sub_repo": "foal", "incubating": True}


def test_classify_hyphenated_project():
    """empire-db is a project name with a hyphen — split only on first hyphen."""
    result = classify_repo("empire-db")
    assert result["project"] == "empire"
    assert result["sub_repo"] == "db"


# --- build_project_map ---

def test_build_project_map_groups_repos():
    repos = [
        {"name": "kafka", "fork": False, "archived": False, "default_branch": "main"},
        {"name": "kafka-site", "fork": False, "archived": False, "default_branch": "main"},
        {"name": "kafka-python", "fork": False, "archived": False, "default_branch": "main"},
    ]
    result = build_project_map(repos)
    assert "kafka" in result
    assert len(result["kafka"]["repos"]) == 3


def test_build_project_map_skips_forks():
    repos = [
        {"name": "kafka", "fork": False, "archived": False, "default_branch": "main"},
        {"name": "some-fork", "fork": True, "archived": False, "default_branch": "main"},
    ]
    result = build_project_map(repos)
    assert "some" not in result


def test_build_project_map_detects_incubating():
    repos = [
        {"name": "incubator-xyz", "fork": False, "archived": False, "default_branch": "main"},
    ]
    result = build_project_map(repos)
    assert result["xyz"]["incubating"] is True


def test_build_project_map_detects_all_archived():
    repos = [
        {"name": "oldproject", "fork": False, "archived": True, "default_branch": "main"},
        {"name": "oldproject-docs", "fork": False, "archived": True, "default_branch": "main"},
    ]
    result = build_project_map(repos)
    assert result["oldproject"]["archived"] is True


def test_build_project_map_not_archived_if_any_active():
    repos = [
        {"name": "myproj", "fork": False, "archived": False, "default_branch": "main"},
        {"name": "myproj-old", "fork": False, "archived": True, "default_branch": "trunk"},
    ]
    result = build_project_map(repos)
    assert result["myproj"]["archived"] is False

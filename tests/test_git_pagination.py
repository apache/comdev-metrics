"""Tests for pagination caps / truncation flags in collectors/git_activity.py."""

from datetime import datetime

import pytest

from asfmetrics.collectors import git_activity as GA


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.headers = {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _commit(i):
    return {
        "commit": {"author": {"date": "2026-10-01T00:00:00Z", "name": f"n{i}"}},
        "author": {"login": f"user{i}"},
    }


def _pr(i, created="2026-10-01T00:00:00Z"):
    return {"created_at": created, "merged_at": None, "closed_at": None, "state": "open"}


def _pager(total, make):
    """Fake httpx.get serving `total` items, PER_PAGE per page."""
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        page = params["page"]
        calls.append(page)
        start = (page - 1) * GA.PER_PAGE
        return FakeResp([make(i) for i in range(start, min(start + GA.PER_PAGE, total))])

    return fake_get, calls


SINCE = datetime(2025, 11, 1)


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr(GA, "_check_rate_limit", lambda: None)
    monkeypatch.setattr(GA, "_update_rate_limit", lambda resp: None)


def test_commits_under_cap_not_truncated(monkeypatch):
    fake, calls = _pager(250, _commit)
    monkeypatch.setattr(GA.httpx, "get", fake)
    commits, truncated = GA._fetch_github_commits("apache", "x", SINCE, max_pages=5)
    assert len(commits) == 250
    assert truncated is False
    assert calls == [1, 2, 3]


def test_commits_exact_multiple_not_truncated(monkeypatch):
    fake, _ = _pager(300, _commit)
    monkeypatch.setattr(GA.httpx, "get", fake)
    commits, truncated = GA._fetch_github_commits("apache", "x", SINCE, max_pages=5)
    assert len(commits) == 300
    assert truncated is False


def test_commits_cap_sets_truncated(monkeypatch):
    fake, calls = _pager(1000, _commit)
    monkeypatch.setattr(GA.httpx, "get", fake)
    commits, truncated = GA._fetch_github_commits("apache", "x", SINCE, max_pages=3)
    assert len(commits) == 300
    assert truncated is True
    assert calls == [1, 2, 3]


def test_commits_unlimited(monkeypatch):
    fake, _ = _pager(1000, _commit)
    monkeypatch.setattr(GA.httpx, "get", fake)
    commits, truncated = GA._fetch_github_commits("apache", "x", SINCE, max_pages=0)
    assert len(commits) == 1000
    assert truncated is False


def test_prs_cap_sets_truncated(monkeypatch):
    fake, _ = _pager(1000, _pr)
    monkeypatch.setattr(GA.httpx, "get", fake)
    prs, truncated = GA._fetch_github_prs("apache", "x", SINCE, max_pages=2)
    assert len(prs) == 200
    assert truncated is True


def test_prs_stop_at_window_not_truncated(monkeypatch):
    fake, calls = _pager(1000, lambda i: _pr(i, created="2020-01-01T00:00:00Z"))
    monkeypatch.setattr(GA.httpx, "get", fake)
    prs, truncated = GA._fetch_github_prs("apache", "x", SINCE, max_pages=2)
    assert prs == []
    assert truncated is False
    assert calls == [1]


def test_page_caps_from_config():
    assert GA._page_caps({}) == (GA.DEFAULT_MAX_COMMIT_PAGES, GA.DEFAULT_MAX_PR_PAGES)
    cfg = {"data_sources": {"git": {"max_commit_pages": 0, "max_pr_pages": 100}}}
    assert GA._page_caps(cfg) == (0, 100)


def test_result_carries_truncation_flag():
    cache = {
        "repos_data": {"x": {"2099-01": {"commits": 3, "committers": 1, "committer_list": ["a"],
                                         "prs_opened": 1, "prs_merged": 0, "prs_closed": 0}}},
        "_truncated": {"x": ["commits"]},
    }
    result = GA._build_result_from_cache("p", "github", cache, org="apache", repos=["x"])
    assert result["truncated"] is True
    assert result["truncated_repos"] == {"x": ["commits"]}


def test_result_not_truncated_by_default():
    result = GA._build_result_from_cache("p", "github", {"repos_data": {}}, org="apache", repos=[])
    assert result["truncated"] is False
    assert "truncated_repos" not in result

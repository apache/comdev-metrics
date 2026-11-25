"""Bots and draft PRs are excluded from git counts (T2, T3)."""

from datetime import UTC, datetime

import pytest

from asfmetrics.collectors import git_activity as GA

SINCE = datetime(2026, 1, 1, tzinfo=UTC)
WHEN = datetime(2026, 10, 5, tzinfo=UTC)


@pytest.fixture
def fake_fetch(monkeypatch):
    commits = [
        {"date": WHEN, "author": "alice", "login": "alice", "name": "Alice", "email": "a@x.org"},
        {"date": WHEN, "author": "alice", "login": "alice", "name": "Alice", "email": "a@x.org"},
        {"date": WHEN, "author": "dependabot[bot]", "login": "dependabot[bot]", "name": "dependabot[bot]",
         "email": "1+dependabot[bot]@users.noreply.github.com"},
        {"date": WHEN, "author": "asfgit", "login": None, "name": "asfgit", "email": "git@apache.org"},
    ]
    prs = [
        {"created_at": "2026-10-01T00:00:00Z", "merged_at": "2026-10-02T00:00:00Z",
         "closed_at": "2026-10-02T00:00:00Z", "state": "closed", "draft": False, "author": "alice"},
        {"created_at": "2026-10-03T00:00:00Z", "merged_at": None, "closed_at": None,
         "state": "open", "draft": True, "author": "bob"},
        {"created_at": "2026-10-04T00:00:00Z", "merged_at": None, "closed_at": None,
         "state": "open", "draft": False, "author": "carol"},
    ]
    monkeypatch.setattr(GA, "_fetch_github_commits", lambda *a, **k: (commits, False))
    monkeypatch.setattr(GA, "_fetch_github_prs", lambda *a, **k: (prs, False))


def test_bots_and_drafts_excluded(fake_fetch):
    per_repo, _ = GA._aggregate_github_monthly(["x"], "apache", SINCE, None)
    m = per_repo["x"]["2026-10"]
    assert m["commits"] == 2
    assert m["committers"] == 1
    assert m["committer_list"] == ["alice"]
    assert m["bot_commits"] == 2
    assert m["prs_opened"] == 2
    assert m["prs_merged"] == 1
    assert m["draft_prs"] == 1


def test_config_can_exempt_a_bot(fake_fetch):
    bots = (frozenset(), frozenset({"asfgit"}))
    per_repo, _ = GA._aggregate_github_monthly(["x"], "apache", SINCE, None, bots=bots)
    m = per_repo["x"]["2026-10"]
    assert m["commits"] == 3 and m["bot_commits"] == 1


def test_excluded_totals_in_result():
    cache = {"repos_data": {"x": {"2099-01": {
        "commits": 2, "committers": 1, "committer_list": ["alice"],
        "prs_opened": 1, "prs_merged": 1, "prs_closed": 0,
        "bot_commits": 5, "draft_prs": 3,
    }}}}
    result = GA._build_result_from_cache("p", "github", cache, org="apache", repos=["x"])
    assert result["excluded"] == {"bot_commits": 5, "draft_prs": 3}

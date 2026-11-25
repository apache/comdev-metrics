"""Tests for repairing zero participant counts in cached mailing-list data."""

from asfmetrics.collectors import mailing_lists as ML


def test_backfill_repairs_only_months_with_mail(monkeypatch):
    monkeypatch.setattr(ML.CACHE, "participant_window_start_str", lambda: "2026-01")
    calls = []

    def fake_numparts(list_name, domain, month_key, base_url=None):
        calls.append(month_key)
        return {"2026-05": 7, "2026-06": 9}.get(month_key, 0)

    monkeypatch.setattr(ML, "_fetch_month_numparts", fake_numparts)

    active = {"2025-11": 5, "2026-05": 34, "2026-06": 54, "2026-07": 0, "2026-10": 7, "2026-11": 11}
    parts = {"2025-11": 0, "2026-05": 0, "2026-10": 4, "2026-11": 3}  # 2026-06 missing

    repaired = ML._backfill_missing_participants(
        "dev", "uima.apache.org", active, parts, skip={"2026-11"}
    )

    assert repaired == 2
    assert parts["2026-05"] == 7 and parts["2026-06"] == 9
    assert parts["2026-10"] == 4          # already nonzero: untouched
    assert sorted(calls) == ["2026-05", "2026-06"]  # not outside window, not 0-mail, not skipped


def test_backfill_leaves_zero_when_api_fails(monkeypatch):
    monkeypatch.setattr(ML.CACHE, "participant_window_start_str", lambda: "2026-01")
    monkeypatch.setattr(ML, "_fetch_month_numparts", lambda *a, **k: None)
    parts = {"2026-05": 0}
    assert ML._backfill_missing_participants("dev", "x.apache.org", {"2026-05": 3}, parts) == 0
    assert parts["2026-05"] == 0

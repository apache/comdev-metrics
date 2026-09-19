"""Tests for trends.py — activity trend classification logic."""

from datetime import date

from asfmetrics.trends import _determine_quarters, _compute_trend


# --- _determine_quarters ---

def test_determine_quarters_mid_month():
    """Jul 10 2026: recent = Apr-Jun, prior = Jan-Mar."""
    result = _determine_quarters(today=date(2026, 7, 10))
    assert result["prior_months"] == ["2026-01", "2026-02", "2026-03"]
    assert result["recent_months"] == ["2026-04", "2026-05", "2026-06"]


def test_determine_quarters_jan():
    """Jan 15 2026: recent = Oct-Dec 2025, prior = Jul-Sep 2025."""
    result = _determine_quarters(today=date(2026, 1, 15))
    assert result["prior_months"] == ["2025-07", "2025-08", "2025-09"]
    assert result["recent_months"] == ["2025-10", "2025-11", "2025-12"]


def test_determine_quarters_first_of_month():
    """Mar 1 2026: current month (Mar) excluded. recent = Dec-Feb, prior = Sep-Nov."""
    result = _determine_quarters(today=date(2026, 3, 1))
    assert result["recent_months"] == ["2025-12", "2026-01", "2026-02"]
    assert result["prior_months"] == ["2025-09", "2025-10", "2025-11"]


def test_determine_quarters_has_labels():
    result = _determine_quarters(today=date(2026, 7, 10))
    assert "prior_label" in result
    assert "recent_label" in result
    assert "window_description" in result
    assert "2026" in result["recent_label"]


# --- _compute_trend ---

def test_compute_trend_growth():
    data = {"2026-01": 10, "2026-02": 10, "2026-03": 10,
            "2026-04": 15, "2026-05": 15, "2026-06": 15}
    pct, recent, prior = _compute_trend(
        data,
        recent_months=["2026-04", "2026-05", "2026-06"],
        prior_months=["2026-01", "2026-02", "2026-03"],
    )
    assert prior == 30
    assert recent == 45
    assert pct == 50.0  # (45-30)/30 * 100


def test_compute_trend_decline():
    data = {"2026-01": 20, "2026-02": 20, "2026-03": 20,
            "2026-04": 10, "2026-05": 10, "2026-06": 10}
    pct, recent, prior = _compute_trend(
        data,
        recent_months=["2026-04", "2026-05", "2026-06"],
        prior_months=["2026-01", "2026-02", "2026-03"],
    )
    assert prior == 60
    assert recent == 30
    assert pct == -50.0


def test_compute_trend_zero_prior():
    """If prior is zero, percent change should be None."""
    data = {"2026-04": 10, "2026-05": 10, "2026-06": 10}
    pct, recent, prior = _compute_trend(
        data,
        recent_months=["2026-04", "2026-05", "2026-06"],
        prior_months=["2026-01", "2026-02", "2026-03"],
    )
    assert prior == 0
    assert recent == 30
    assert pct is None


def test_compute_trend_missing_months():
    """Missing months should be treated as 0."""
    data = {"2026-01": 100}
    pct, recent, prior = _compute_trend(
        data,
        recent_months=["2026-04", "2026-05", "2026-06"],
        prior_months=["2026-01", "2026-02", "2026-03"],
    )
    assert prior == 100
    assert recent == 0
    assert pct == -100.0


def test_compute_trend_no_change():
    data = {"2026-01": 10, "2026-02": 10, "2026-03": 10,
            "2026-04": 10, "2026-05": 10, "2026-06": 10}
    pct, _recent, _prior = _compute_trend(
        data,
        recent_months=["2026-04", "2026-05", "2026-06"],
        prior_months=["2026-01", "2026-02", "2026-03"],
    )
    assert pct == 0.0

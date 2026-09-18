"""Tests for collectors/cache.py — shared caching utilities."""

from datetime import datetime
from pathlib import Path

from asfmetrics.collectors.cache import (
    cache_is_current,
    collector_cache_dir,
    current_month_str,
    invalidate,
    load_cache,
    save_cache,
    twelve_months_ago,
    twelve_months_ago_str,
)


# --- Date helpers ---

def test_current_month_str_format():
    result = current_month_str()
    assert len(result) == 7  # YYYY-MM
    assert result[4] == "-"
    year, month = result.split("-")
    assert 2020 <= int(year) <= 2100
    assert 1 <= int(month) <= 12


def test_twelve_months_ago_returns_datetime():
    result = twelve_months_ago()
    assert isinstance(result, datetime)
    now = datetime.now()
    assert result.year == now.year - 1
    assert result.month == now.month


def test_twelve_months_ago_str_format():
    result = twelve_months_ago_str()
    assert len(result) == 7
    assert result[4] == "-"


def test_twelve_months_ago_str_matches_datetime():
    dt = twelve_months_ago()
    s = twelve_months_ago_str()
    assert s == f"{dt.year}-{dt.month:02d}"


# --- cache_is_current ---

def test_cache_is_current_today():
    today = datetime.now().strftime("%Y-%m-%d")
    assert cache_is_current({"_fetched_at": today}) is True


def test_cache_is_current_yesterday():
    assert cache_is_current({"_fetched_at": "2020-01-01"}) is False


def test_cache_is_current_missing():
    assert cache_is_current({}) is False


# --- Directory + file operations ---

def test_collector_cache_dir_creates_subdir(tmp_path):
    config = {"output": {"json_dir": str(tmp_path / "data")}}
    result = collector_cache_dir(config, "test_collector")
    assert result.exists()
    assert result.name == "test_collector"
    assert result.parent.name == "_cache"


def test_save_and_load_cache(tmp_path):
    config = {"output": {"json_dir": str(tmp_path / "data")}}
    data = {"lists": ["dev", "user"], "count": 42}
    save_cache("myproject", data, config, "test_collector")
    loaded = load_cache("myproject", config, "test_collector")
    assert loaded == data


def test_load_cache_missing(tmp_path):
    config = {"output": {"json_dir": str(tmp_path / "data")}}
    assert load_cache("nonexistent", config, "test_collector") is None


def test_invalidate_clears_files(tmp_path):
    config = {"output": {"json_dir": str(tmp_path / "data")}}
    save_cache("proj_a", {"a": 1}, config, "test_collector")
    save_cache("proj_b", {"b": 2}, config, "test_collector")
    cache_dir = collector_cache_dir(config, "test_collector")
    assert len(list(cache_dir.glob("*.json"))) == 2
    invalidate(config, "test_collector")
    assert len(list(cache_dir.glob("*.json"))) == 0

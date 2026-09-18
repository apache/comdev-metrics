"""Tests for config.py — configuration loading and path helpers."""

from pathlib import Path

import pytest

from asfmetrics.config import (
    DEFAULT_JSON_DIR,
    CACHE_SUBDIR,
    STATE_SUBDIR,
    PROJECT_MAP_FILE,
    get_json_dir,
    get_cache_dir,
    get_state_dir,
    load_config,
)


# --- Path helpers ---

def test_get_json_dir_from_config(tmp_path):
    config = {"output": {"json_dir": str(tmp_path / "out")}}
    result = get_json_dir(config)
    assert result == tmp_path / "out"
    assert result.exists()


def test_get_json_dir_default(tmp_path, monkeypatch):
    """With no config key, falls back to DEFAULT_JSON_DIR."""
    monkeypatch.chdir(tmp_path)
    result = get_json_dir({})
    assert result == Path(DEFAULT_JSON_DIR)


def test_get_cache_dir(tmp_path):
    config = {"output": {"json_dir": str(tmp_path / "data")}}
    result = get_cache_dir(config)
    assert result == tmp_path / "data" / CACHE_SUBDIR
    assert result.exists()


def test_get_state_dir(tmp_path):
    config = {"output": {"json_dir": str(tmp_path / "data")}}
    result = get_state_dir(config)
    assert result == tmp_path / "data" / STATE_SUBDIR
    assert result.exists()


# --- Constants ---

def test_constants_are_strings():
    assert isinstance(DEFAULT_JSON_DIR, str)
    assert isinstance(CACHE_SUBDIR, str)
    assert isinstance(STATE_SUBDIR, str)
    assert isinstance(PROJECT_MAP_FILE, str)
    assert PROJECT_MAP_FILE.endswith(".json")


# --- load_config ---

def test_load_config_from_file(tmp_path):
    config_file = tmp_path / "config.yml"
    config_file.write_text("projects:\n  - kafka\n  - airflow\n")
    result = load_config(config_file)
    assert result["projects"] == ["kafka", "airflow"]


def test_load_config_missing_raises():
    with pytest.raises(FileNotFoundError):
        load_config(Path("/nonexistent/config.yml"))

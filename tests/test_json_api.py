"""Tests for output/json_api.py — JSON file writing."""

import json

from asfmetrics.output.json_api import write_json


def test_write_json_creates_file(tmp_path):
    config = {"output": {"json_dir": str(tmp_path / "data")}}
    stats = {"project": "kafka", "active_lists": [{"list_name": "dev", "messages": 100}]}
    result = write_json("kafka", stats, config)
    assert result.exists()
    assert result.name == "kafka.json"
    with open(result) as f:
        loaded = json.load(f)
    assert loaded == stats


def test_write_json_creates_directory(tmp_path):
    config = {"output": {"json_dir": str(tmp_path / "deep" / "nested" / "data")}}
    write_json("test", {"x": 1}, config)
    assert (tmp_path / "deep" / "nested" / "data" / "test.json").exists()


def test_write_json_overwrites(tmp_path):
    config = {"output": {"json_dir": str(tmp_path / "data")}}
    write_json("proj", {"version": 1}, config)
    write_json("proj", {"version": 2}, config)
    with open(tmp_path / "data" / "proj.json") as f:
        loaded = json.load(f)
    assert loaded["version"] == 2

"""Tests for bot detection (T2)."""

from asfmetrics.bots import bot_config, is_bot


def test_known_bots():
    assert is_bot(login="dependabot[bot]")
    assert is_bot(login="github-actions")
    assert is_bot(name="asfgit")
    assert is_bot(login="Renovate-Bot")  # case-insensitive


def test_bot_by_email():
    assert is_bot(email="49699333+dependabot[bot]@users.noreply.github.com")


def test_humans_are_not_bots():
    assert not is_bot(login="rbowen", name="Rich Bowen", email="rbowen@apache.org")
    assert not is_bot(login="abbott")  # contains "bot" but isn't one
    assert not is_bot()


def test_config_extra_and_allow():
    extra, allow = bot_config({"data_sources": {"git": {
        "extra_bot_logins": ["Iceberg-Release"],
        "not_bot_logins": ["someone-bot"],
    }}})
    assert is_bot(login="iceberg-release", extra=extra, allow=allow)
    assert not is_bot(login="someone-bot", extra=extra, allow=allow)


def test_bot_config_defaults():
    assert bot_config({}) == (frozenset(), frozenset())

"""Bot account detection shared by the collectors.

A bot is an automated account whose activity should not count as community
participation (dependency updaters, CI, the ASF git mirror, and so on).
Bot activity is excluded from contributor counts and reported separately.

Projects can add their own bots, or exempt a human account that matches a
bot pattern, in config.yml:

    data_sources:
      git:
        extra_bot_logins: [some-project-bot]
        not_bot_logins: [someone-bot]   # a real person
"""

# Exact GitHub logins / git author names (compared case-insensitively)
BOT_LOGINS = frozenset({
    "dependabot",
    "dependabot-preview",
    "github-actions",
    "renovate",
    "renovate-bot",
    "asfgit",
    "asf-ci",
    "asf-ci-deploy",
    "asf-gitbox-commits",
    "copilot",
    "web-flow",
    "snyk-bot",
    "pre-commit-ci",
    "allcontributors",
    "codecov",
    "mergify",
    "greenkeeper",
})

# Login / name suffixes that mark an automated account
BOT_SUFFIXES = ("[bot]", "-bot", "_bot")


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def is_bot(
    login: str | None = None,
    name: str | None = None,
    email: str | None = None,
    extra: frozenset[str] | set[str] = frozenset(),
    allow: frozenset[str] | set[str] = frozenset(),
) -> bool:
    """Return True if the login, author name or email belongs to a bot.

    Args:
        login: GitHub login, if known.
        name: git author name.
        email: git author email.
        extra: additional bot logins/names (lower-case) from config.
        allow: logins/names (lower-case) that must never be treated as bots.
    """
    ids = [i for i in (_norm(login), _norm(name)) if i]
    if any(i in allow for i in ids):
        return False
    for i in ids:
        if i in BOT_LOGINS or i in extra or i.endswith(BOT_SUFFIXES):
            return True
    # GitHub App accounts commit as <id>+<app>[bot]@users.noreply.github.com
    return "[bot]@" in _norm(email)


def bot_config(config: dict) -> tuple[frozenset[str], frozenset[str]]:
    """Read (extra, allow) bot lists from config, lower-cased."""
    git = config.get("data_sources", {}).get("git", {})
    extra = frozenset(_norm(x) for x in git.get("extra_bot_logins", []) or [])
    allow = frozenset(_norm(x) for x in git.get("not_bot_logins", []) or [])
    return extra, allow

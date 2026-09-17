# ASF Community Development Metrics

Public dashboard showing community activity metrics for Apache projects,
with 12-month trend lines for meaningful context.

**Status**: Working dashboard deployed at https://apache.github.io/comdev-metrics/
— fetches foundation data from projects.apache.org, mailing list stats from
Pony Mail Foal API, Git/GitHub activity (with SVN support), new committer dates
from Whimsy LDAP, and renders a per-project dashboard with trend lines,
releases, community growth, and activity trend classifications.

## Quick Start

```bash
cd /path/to/comdev-metrics
cp config.example.yml config.yml
cp .secrets.example .secrets
# Edit .secrets with your GitHub token
# Edit config.yml as needed

# Run with uv (no install needed)
uv run asfmetrics

# Single project
uv run asfmetrics --project comdev

# Skip mailing lists (just fetch foundation + git data)
uv run asfmetrics --skip-mailing-lists

# Skip git/VCS collection
uv run asfmetrics --skip-git

# Force re-fetch everything (bypass cache)
uv run asfmetrics --force-refresh

# Re-fetch the GitHub repo inventory
uv run asfmetrics --refresh-repos

# View results
cd site && python3 -m http.server 8888
# Open http://localhost:8888
```

## What It Does

1. **Fetches** foundation-wide data from projects.apache.org JSON files (committees, rosters, releases, podlings, repositories)
2. **Detects** new committers via Whimsy LDAP `createTimestamp`, cross-referenced with project group membership
3. **Detects** roster changes (new committers/PMC members) by diffing committee data between runs
4. **Discovers** all mailing lists per project via Pony Mail Foal `preferences.json`
5. **Collects** per-list message stats for a 12-month rolling window (with aggressive caching — past months are never re-fetched)
6. **Collects** Git/VCS activity per project (commits, committers, PRs opened/merged) via GitHub API or SVN log
7. **Classifies** project activity trends via deterministic quarter-over-quarter analysis (Sharp Decline / Declining / Dormant)
8. **Writes** everything to a JSON data store (`site/data/`)
9. **Publishes** a static HTML + JS dashboard with:
   - **Overview**: community growth, releases, mailing list activity rankings, all projects table
   - **Activity Trends**: projects flagged as declining or dormant, with methodology and thresholds
   - **Per-project pages**: mailing lists, git repos, releases, community growth, trend badges
   - Links to projects.apache.org for full project metadata (roster, repos, homepage)

Only lists with actual traffic in the 12-month window are shown.

## Caching

Data is aggressively cached to minimize API calls:

- **Past months are immutable.** Once a month ends, its data can never change in
  the archive or git history. Cached data for completed months is never re-fetched.
- **Only the current month is refreshed** on each run (since it's still in progress).
- **Same-day re-runs skip** (cache hit) — no redundant API calls during testing.
- **Cache locations:**
  - Mailing lists: `site/data/_cache/mailing_lists/<project>.json`
  - Git activity: `site/data/_cache/git/<project>.json`
- **Force refresh:** Use `--force-refresh` to clear all caches and re-fetch everything.

On a typical weekly run mid-month, the mailing list phase completes in seconds
(cache hits from prior runs) instead of making hundreds of API calls.

## Configuration

See `config.example.yml`. Config is searched in order:
1. `./config.yml`
2. `~/.asfmetrics/config.yml`
3. `/etc/asfmetrics/config.yml`

### Secrets

GitHub token (needed for git activity collection; optional but strongly recommended):
1. `GITHUB_TOKEN` environment variable
2. `.secrets` file in the project directory (line: `GITHUB_TOKEN=ghp_...`)
3. `~/.secrets` file (user-level fallback)
4. `config.yml` `data_sources.git.token` field

Copy `.secrets.example` → `.secrets` and fill in your token.
The `.secrets` file is in `.gitignore` and will never be committed.

### Per-project VCS overrides

Most projects use GitHub. For projects still on Subversion, add an override
in `config.yml`:

```yaml
project_overrides:
  httpd:
    vcs: svn
    svn_path: https://svn.apache.org/repos/asf/httpd/httpd/trunk
```

SVN-only projects can also be auto-detected from `repositories.json` —
if a project has SVN repos but no GitHub repos, the collector automatically
uses `svn log`.

See `config.example.yml` for full documentation of override options.

## Project Structure

```
comdev-metrics/
├── .secrets.example         # Template for secrets (GitHub token)
├── config.example.yml       # Example configuration
├── pyproject.toml           # uv/hatch project definition
├── src/asfmetrics/
│   ├── __init__.py         # Package version
│   ├── cli.py              # Entry point — orchestrates all phases
│   ├── config.py           # Config loading (YAML, multi-path lookup)
│   ├── health.py           # Deterministic activity trend classification
│   ├── collectors/
│   │   ├── mailing_lists.py         # Pony Mail Foal API + caching
│   │   ├── git_activity.py          # GitHub API + SVN log collector + caching
│   │   ├── github_repos.py          # Repo inventory + project classification
│   │   └── projects_apache_org.py   # Foundation JSON + Whimsy LDAP + roster differ
│   ├── analysis/           # Trend calculations (placeholder)
│   └── output/
│       └── json_api.py     # JSON data writer
├── site/
│   ├── index.html          # Overview dashboard (tabs: All Projects, Growth, Releases, Mailing Lists, Activity Trends)
│   ├── project.html        # Per-project detail page (?id=projectname)
│   ├── about.html          # Data sources and methodology documentation
│   └── data/               # Generated JSON + cache (git-ignored)
│       ├── _cache/
│       │   ├── mailing_lists/  # Per-project mailing list cache
│       │   ├── git/            # Per-project git activity cache
│       │   ├── committees.json
│       │   ├── releases.json
│       │   ├── new_committers.json
│       │   ├── mailing_summary.json
│       │   └── project_health.json
│       ├── _state/             # Roster diff state between runs
│       ├── _project_map.json   # GitHub repo → project classification
│       ├── <project>.json      # Mailing list data
│       └── <project>_git.json  # Git activity data
├── DATA_SOURCES.md         # Where all the data comes from
├── PLAN.md                 # Execution plan and milestones
└── LICENSE                 # Apache License 2.0
```

## CLI Reference

```
usage: asfmetrics [-h] [--config CONFIG] [--project PROJECT]
                  [--skip-mailing-lists] [--skip-git]
                  [--force-refresh] [--refresh-repos]

Options:
  --config CONFIG       Path to config.yml (default: auto-discover)
  --project PROJECT     Run for a single project only
  --skip-mailing-lists  Skip mailing list collection
  --skip-git            Skip git/VCS activity collection
  --force-refresh       Clear all caches and re-fetch everything
  --refresh-repos       Re-fetch the GitHub repo inventory (project → repos map)
```

### Collection Phases

The CLI runs these phases in order:

1. **Repo inventory** — GitHub org listing → `_project_map.json` (only when needed: first run, `--refresh-repos`, or `--force-refresh`)
2. **Foundation data** — projects.apache.org JSON + Whimsy LDAP new committer dates + roster diffing
3. **Mailing lists** — per-project Pony Mail stats (skipped with `--skip-mailing-lists`) + summary file
4. **Git/VCS activity** — per-project GitHub API or SVN log (skipped with `--skip-git`)
5. **Activity trend classification** — deterministic QoQ trend analysis → `project_health.json`

## Dashboard Pages

### index.html — Overview

Five tabs:
- **All Projects** (default): alphabetical table of all active PMCs with established date, roster size, chair
- **Community Growth**: two-color bar chart (blue = new committers, orange = new PMC members)
- **Recent Releases**: ranked by release count
- **Mailing Lists**: all lists ranked by 12-month message volume
- **Activity Trends**: projects classified as Sharp Decline, Declining, or Dormant with methodology

### project.html — Per-Project Detail

- Stat cards: messages, active lists, PMC size, releases, established date
- Activity trend badge (if applicable)
- Mailing list table with sparklines → click to expand full bar chart with trend line
- Git repos table with sparklines → click to expand commit chart + PR chart
- Recent releases (collapsed after 10)
- Community growth: new committers with names and dates
- Link to projects.apache.org for full metadata

### about.html — Data Documentation

Explains all data sources, methodology, what's measured, and limitations.

## Deployment

**Production**: https://apache.github.io/comdev-metrics/ — built and deployed
via GitHub Actions.

The GitHub Actions workflow (`.github/workflows/metrics.yml`):
1. Downloads the previously-deployed site (contains cached data from prior runs)
2. Copies `config.example.yml` → `config.yml`
3. Runs the full collection pipeline (`uv run asfmetrics`)
4. Uploads the entire `site/` directory as a Pages artifact (14-day retention)
5. Deploys to GitHub Pages

No files in the repository are modified by the build — only the Pages artifact
is updated. The GitHub Actions-provided `GITHUB_TOKEN` handles API
authentication automatically (ASF has GitHub Enterprise rate limits).

Currently triggered manually (`workflow_dispatch`); scheduled runs TBD.

### Local development

For local testing:
```bash
cp config.example.yml config.yml
cp .secrets.example .secrets   # add your GitHub token
uv run asfmetrics --project comdev
```

**Planned**: Serve at `https://projects.apache.org/metrics` (via Alias or rewrite from the ComDev VM).

## License

Apache License 2.0

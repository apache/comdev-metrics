# ComDev Metrics Site — Execution Plan

Public, automated dashboard at **community.apache.org/metrics/** showing
activity of every Apache project with 12-month rolling trends.

## Design Principles

- **Trends, not absolutes** — 12-month rolling window with linear regression trend lines
- **Aggressive caching** — past months are immutable; only the current month is refreshed
- **Python/uv** — anyone can clone and test locally with `uv run`
- **Very configurable** — a project can run it for just themselves
- **VCS-agnostic** — GitHub API by default, SVN for projects that use it (auto-detected or configured)
- **Public** — unlike Reporter, visible to everyone
- **Static output** — generated HTML + JS frontend, no live server
- **JSON data store** — collectors write JSON; frontend reads client-side
- **No data duplication** — link to projects.apache.org for project metadata

## Data Domains

### 1. Mailing List Metrics
- Message volume (per-list, 12-month rolling window)
- Unique posters
- Thread count
- Source: Pony Mail Foal API (`POST /api/stats.json`)
- **Caching**: Past months immutable; only current month re-fetched
- **Summary file**: `_cache/mailing_summary.json` (avoids 200+ fetches on dashboard load)

### 2. Git/VCS Metrics
- Commits per month (12-month window)
- Unique committers per month
- PRs opened / merged / closed (GitHub only)
- Source: GitHub API (zero-checkout, API-only) OR `svn log --xml` (remote, no checkout)
- **Auto-detection**: SVN-only projects detected from `repositories.json`
- **Per-project VCS config**: `project_overrides` in config.yml

### 3. Community Events
- New committers — detected via Whimsy LDAP `createTimestamp`, cross-referenced with `people.json` group membership
- New PMC members — from roster dates in committees data
- Releases published
- Source: projects.apache.org JSON, Whimsy public JSON (`public_ldap_people.json`)

### 4. Project Health Classification
- Deterministic quarter-over-quarter trend analysis
- Categories: Sharp Decline, Declining (At Risk), Dormant
- Only human discussion lists counted (dev, user, users, general, discuss)
- Fixed thresholds, no ML/heuristics
- Output: `_cache/project_health.json`

### 5. Project Lifecycle
- New projects (graduated from Incubator)
- Retirements to Attic
- Source: Incubator status page, board minutes

## Milestones

| # | Milestone | Status |
|---|-----------|--------|
| 1 | Scaffold project (pyproject.toml, config loading, CLI) | ✅ Done |
| 2 | Mailing list collector (Pony Mail Foal API, 12-month window + caching) | ✅ Done |
| 3 | Git/GitHub collector + SVN backend (per-repo, rate-limit aware) | ✅ Done |
| 4 | Trend analysis (12-month rolling window + trend lines with current-month extrapolation) | ✅ Done |
| 5 | Static HTML dashboard + per-project pages (default: All Projects tab) | ✅ Done |
| 6 | Roster change detection (projects.apache.org JSON diffing) | ✅ Done |
| 7 | New committer detection (Whimsy LDAP createTimestamp) | ✅ Done |
| 8 | Project health classification (deterministic QoQ trend analysis) | ✅ Done |
| 9 | About page (data source documentation for end users) | ✅ Done |
| 10 | Deploy to ComDev VM for demo | ✅ Done |
| 11 | Next Committer integration (PMC-only, LDAP gated) | ⬜ |
| 12 | Production deployment (GitHub Pages) | ✅ Done |

**Status:** Dashboard running at https://boxofclue.com/comdev-metrics/
with 205+ projects collecting successfully.

## Architecture

### Collection Pipeline (CLI phases)

```
Phase 0: Repo inventory (if needed)
  └─ GitHub org listing → _project_map.json (auto-run on first use, or --refresh-repos)

Phase 1: Foundation data
  └─ projects.apache.org JSON → committees, podlings, releases, repos, people
  └─ Whimsy LDAP → new committer dates (createTimestamp)
  └─ Roster diffing → new PMC members / retired projects

Phase 2: Mailing lists (per-project)
  └─ Pony Mail Foal API → per-list monthly message counts
  └─ Writes per-project JSON + _cache/mailing_summary.json

Phase 3: Git/VCS activity (per-project)
  └─ GitHub API (commits + PRs) or SVN log
  └─ Per-repo monthly time-series

Phase 4: Health classification
  └─ QoQ trend analysis → project_health.json
```

### Caching Strategy
- **Mailing lists**: `site/data/_cache/mailing_lists/<project>.json`
- **Git activity**: `site/data/_cache/git/<project>.json` (per-repo monthly data)
- Past months are immutable — data cannot change after a month ends
- Same-day re-runs skip (cache hit); next-day runs do incremental refresh from last fetch date
- Incremental refresh overlaps by re-fetching from the fetch date (not day-after) to avoid gaps
- `--force-refresh` clears all caches
- `--refresh-repos` re-fetches the GitHub org repo inventory

### Trend Lines
- Linear regression (least-squares) over the 12-month data series
- Current (incomplete) month is extrapolated to full-month projection before regression
- Extrapolation: `projected = actual × (days_in_month / day_of_month)`
- Rendered as dashed SVG overlay on per-project bar charts

### Health Classification (health.py)

Quarter-over-quarter comparison using fixed thresholds:

| Category | Criteria |
|----------|----------|
| **Sharp Decline** | Both ML discussion and git commits down ≥30% QoQ |
| **Declining (At Risk)** | One axis down ≥30% (with meaningful prior activity ≥30), other not growing ≥30% |
| **Dormant** | ≤5 commits AND ≤5 messages in recent quarter, ≤20 total 12-month commits |

Only human discussion lists counted (dev, user, users, general, discuss).
Current partial month excluded. Projects must have data files to be assessed.

### Per-project Detail Pages
- Link to projects.apache.org for full metadata (roster, repos, homepage)
- No roster duplication — just show PMC size stat and link out
- Git section: clickable table of repos (sparklines), click to expand chart
- Mailing list section: same pattern — clickable list table, chart on click
- First/most-active item auto-expanded on page load
- Releases collapsed after 10 with "show more" expander
- Activity trend badge (Sharp Decline / Declining / Dormant) shown when applicable
- Community Growth section: new committers with names and dates

### Rate Limiting (GitHub API)
- Tracks `x-ratelimit-remaining` from every response
- Auto-pauses and waits for reset when remaining ≤ 50
- Budget displayed inline every 20 projects + at end of git phase

## Deployment

### GitHub Actions Workflow (Production)

Sebb set up a GitHub Actions workflow that:
1. Runs the full collection pipeline (foundation data → mailing lists → git → health)
2. Uploads the output `site/` directory as a runtime artifact (caches between runs)
3. Deploys to GitHub Pages at https://apache.github.io/comdev-metrics/

The build does not update any files in the repository itself — only the
artifact/Pages output. GitHub Actions provides a temporary `GITHUB_TOKEN`
with sufficient rate limits (ASF has GitHub Enterprise: 15,000 req/hr).

GitHub Pages enabled via [INFRA-28405](https://issues.apache.org/jira/browse/INFRA-28405).

First full run took ~2 hours (mostly git activity fetch); subsequent runs
should be much faster due to caching (past months immutable).

### Development/Staging — boxofclue.com/comdev-metrics/

Rich's local cron on matrim.rcbowen.com → rsync to boxofclue.com:
```
0 6 * * 1  rcbowen  cd /home/rbowen/devel/apache/comdev/comdev-metrics && /usr/bin/uv run asfmetrics --config config.yml && rsync -az --delete site/ fagin.rcbowen.com:/var/www/vhosts/boxofclue.com/comdev-metrics/
```

### Future: projects.apache.org/metrics

The plan is to serve the metrics at `https://projects.apache.org/metrics`
by fetching the GitHub Pages artifact to the ComDev VM, or using an Alias/rewrite.
The ComDev VM already hosts projects.apache.org and reporter.apache.org.
Longer term: tighter integration between the metrics dashboard and projects.apache.org
(cross-linking, embedded sparklines, health badges on project pages).

## Open Questions

| Question | Notes | Status |
|----------|-------|--------|
| Definitive data sources? | projects.a.o is secondary and may go away. Whimsy? LDAP? | Open |
| Next Committer ↔ LDAP? | PMC-only access. Needs ASF Infra ticket for service account or OAuth. | Open |
| Bot filtering? | Measure contributions by PMC, committers, everyone else — and bots separately | Open |
| Location on projects.a.o? | Serve at projects.apache.org/metrics via Alias/rewrite from GH Pages | Discussion active (Sep 2026) |
| Podling display names? | Podlings show as IDs (e.g. "maka") not "Apache Maka (Incubating)" | [Issue #4](https://github.com/apache/comdev-metrics/issues/4) |
| Include podlings at all? | Incubator projects don't fall under ComDev purview; may exclude entirely | Under discussion |
| Style alignment with projects.a.o? | Metrics pages look different from projects.apache.org — cosmetic, not urgent | Low priority |
| ATR release data integration? | Dave Fisher's Tooling team working on release-catalog.apache.org; could improve release data | Discuss at Glasgow CotC |

## Discussion History

Key threads on dev@community.apache.org:

| Date | Thread | Summary |
|------|--------|---------|
| Jul 12 | "Project metrics" | Rich proposes the dashboard, asks if ComDev wants it as a service |
| Sep 4–14 | "Advice/suggestions for publishing metrics to projects.apache.org" | Deployment options: SVN/VM (Dave), rewrite/Alias (Sebb), GitHub Actions (Sebb + Jarek). Sebb volunteers to set up GHA workflow. Rich asks for thorough documentation to avoid SPOF. |
| Sep 14–16 | "Progress on publishing metrics" | Sebb reports GHA workflow + GH Pages working. First full run ~2 hours. INFRA-28405 enabled GH Pages. Issues: podling names, run time. |
| Sep 16 | "Location for metrics" | Sebb asks whether to serve at projects.a.o/metrics or just link. Rich prefers projects.a.o/metrics. tison reports podling name issues. |

## Configuration

Lookup order:
1. `./config.yml` (project-local)
2. `~/.asfmetrics/config.yml` (user-level)
3. `/etc/asfmetrics/config.yml` (system-level, for ComDev VM)

See `config.example.yml`, `.secrets.example`, and `DATA_SOURCES.md` for details.

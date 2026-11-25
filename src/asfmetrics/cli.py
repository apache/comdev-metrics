"""CLI entry point for asfmetrics."""

import json
import argparse
import sys
import time
from pathlib import Path
from datetime import UTC, datetime

from asfmetrics.config import (
    load_config, get_json_dir, get_cache_dir, PROJECT_MAP_FILE, MAILING_SUMMARY_FILE,
)
from asfmetrics.collectors.mailing_lists import (
    collect_mailing_list_stats,
    invalidate_cache,
    reset_call_counter,
    get_call_counter,
)
from asfmetrics.collectors.git_activity import (
    collect_git_activity,
    invalidate_git_cache,
    get_rate_limit_status,
)
from asfmetrics.collectors.github_repos import collect_repo_inventory
from asfmetrics.collectors.projects_apache_org import (
    collect_projects_apache_org,
)
from asfmetrics.output.json_api import write_json
from asfmetrics.trends import compute_activity_trends


def status(msg: str):
    """Print a single-line status that overwrites itself."""
    sys.stdout.write(f"\r\033[K  {msg}")
    sys.stdout.flush()


def status_done(msg: str):
    """Print a final status line (stays visible)."""
    sys.stdout.write(f"\r\033[K  {msg}\n")
    sys.stdout.flush()

def stamp(msg: str):
    """Print a timing marker (for use in batch jobs)"""
    date = datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    sys.stdout.write(f"\n{date}  {msg}\n")
    sys.stdout.flush()

def _fmt_secs(secs: float) -> str:
    """Format a duration as e.g. '45.2s', '12m 03s' or '1h 05m 09s'."""
    secs = round(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def report_timings(phases: dict, project_times: dict, total: float, top_n: int = 10) -> None:
    """Print a phase breakdown and the slowest projects per phase.

    Args:
        phases: {phase name: seconds}, in run order.
        project_times: {phase name: {project: seconds}}.
        total: wall-clock seconds for the whole run.
        top_n: how many slowest projects to list per phase.
    """
    print(f"\n{'=' * 60}")
    print("  Timing summary")
    print(f"{'=' * 60}")
    width = max((len(p) for p in phases), default=10)
    for name, secs in phases.items():
        share = (secs / total * 100) if total else 0
        print(f"  {name:<{width}}  {_fmt_secs(secs):>12}  {share:5.1f}%")
    print(f"  {'Total':<{width}}  {_fmt_secs(total):>12}")

    for name, times in project_times.items():
        if not times:
            continue
        ranked = sorted(times.items(), key=lambda kv: -kv[1])[:top_n]
        phase_total = sum(times.values())
        print(f"\n  Slowest {len(ranked)} of {len(times)} projects: {name}")
        pw = max(len(p) for p, _ in ranked)
        for project, secs in ranked:
            share = (secs / phase_total * 100) if phase_total else 0
            print(f"    {project:<{pw}}  {_fmt_secs(secs):>12}  {share:5.1f}%")
    print()


def main():
    parser = argparse.ArgumentParser(
        prog="asfmetrics",
        description="Collect and publish Apache project community metrics.",
    )
    parser.add_argument(
        "--config", type=Path, default=None,
        help="Path to config.yml (default: auto-discover)",
    )
    parser.add_argument(
        "--project", type=str, default=None,
        help="Run for a single project only (overrides config)",
    )
    parser.add_argument(
        "--skip-mailing-lists", action="store_true",
        help="Skip mailing list collection (faster for testing)",
    )
    parser.add_argument(
        "--skip-git", action="store_true",
        help="Skip git/VCS activity collection",
    )
    parser.add_argument(
        "--force-refresh", action="store_true",
        help="Ignore cached data and re-fetch everything",
    )
    parser.add_argument(
        "--refresh-repos", action="store_true",
        help="Re-fetch the GitHub repo inventory (project → repos map)",
    )
    parser.add_argument(
        "--timestamp", action="store_true",
        help="Add timestamps",
    )
    args = parser.parse_args()

    run_t0 = time.time()
    phases: dict[str, float] = {}
    project_times: dict[str, dict[str, float]] = {}
    if args.timestamp:
        stamp("Starting")

    try:
        config = load_config(args.config)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    print("asfmetrics: loaded config")

    # Handle --force-refresh: clear caches
    if args.force_refresh:
        invalidate_cache(config)
        invalidate_git_cache(config)
        print("  caches cleared (--force-refresh)")

    # Repo inventory: auto-run if _project_map.json is missing,
    # or if --refresh-repos / --force-refresh is specified.
    json_dir = get_json_dir(config)
    project_map_path = json_dir / PROJECT_MAP_FILE
    need_inventory = (
        args.refresh_repos
        or args.force_refresh
        or not project_map_path.exists()
    )
    if need_inventory and not args.skip_git:
        if args.timestamp:
            stamp("Fetching GitHub repo inventory")
        t0 = time.time()
        status("fetching GitHub repo inventory (apache org)...")
        inv = collect_repo_inventory(config)
        phases["Repo inventory"] = time.time() - t0
        status_done(
            f"repo inventory: {inv['repo_count']} repos → {inv['project_count']} projects"
            f" [{_fmt_secs(phases['Repo inventory'])}]"
        )

    # Phase 1: Fetch foundation-wide data from projects.apache.org
    if args.timestamp:
        stamp("Fetching foundation data")
    t0 = time.time()
    status("fetching foundation data from projects.apache.org...")
    pao_result = collect_projects_apache_org(config)
    write_json("_foundation", pao_result["roster_changes"], config)
    phases["Foundation data"] = time.time() - t0
    status_done(
        f"foundation data: {len(pao_result['active_projects'])} active projects"
        f" [{_fmt_secs(phases['Foundation data'])}]"
    )

    mail_domain_map = pao_result.get("mail_domain_map", {})
    # Determine project list
    projects = config.get("projects", ["all"])
    if args.project:
        projects = [args.project]

    if "all" in projects:
        projects = pao_result["active_projects"]

    # Phase 2: Per-project mailing list collection
    if not args.skip_mailing_lists:
        total = len(projects)
        collected = 0
        skipped = 0
        ml_t0 = time.time()
        mail_times = project_times.setdefault("Mailing lists", {})
        if args.timestamp:
            stamp("Fetching mailing lists")
        for i, project in enumerate(projects, 1):
            if args.timestamp:
                stamp(project)
            status(f"[{i}/{total}] {project}: fetching mailing lists...")
            reset_call_counter()
            p_t0 = time.time()
            stats = collect_mailing_list_stats(project, config, mail_domain_map)
            p_dt = time.time() - p_t0
            mail_times[project] = p_dt
            month_calls = get_call_counter()
            if stats:
                active_count = len(stats["active_lists"])
                total_msgs = sum(lst["messages"] for lst in stats["active_lists"])
                write_json(project, stats, config)
                collected += 1
                # Use status_done so the timing/call-count line PERSISTS
                # (status() uses \r and would be overwritten by the next
                # project, hiding the very numbers we're measuring).
                status_done(
                    f"[{i}/{total}] {project}: {active_count} active lists, "
                    f"{total_msgs} messages "
                    f"[{p_dt:.1f}s, {month_calls} per-month participant calls]"
                )
            else:
                skipped += 1
                status_done(f"[{i}/{total}] {project}: no active lists [{p_dt:.1f}s]")

        ml_dt = time.time() - ml_t0
        status(f"  mailing lists total time: {ml_dt:.1f}s")

        status_done(f"mailing lists: {collected} projects collected, {skipped} skipped (no activity)")

        # Write mailing_summary.json for the overview page (avoids 200+ fetches)
        summary = []
        for project_name in projects:
            project_file = json_dir / f"{project_name}.json"
            if project_file.exists():
                try:
                    with open(project_file, encoding='utf-8') as f:
                        data = json.load(f)
                    for lst in data.get("active_lists", []):
                        summary.append({
                            "project": data.get("project", project_name),
                            "list_name": lst.get("list_name", ""),
                            "messages": lst.get("messages", 0),
                            "active_months": lst.get("active_months", {}),
                        })
                except (json.JSONDecodeError, OSError):
                    pass
        summary_path = get_cache_dir(config) / MAILING_SUMMARY_FILE
        with open(summary_path, "w", encoding='utf-8') as f:
            json.dump(summary, f)
        status_done(f"mailing summary: {len(summary)} lists written to {MAILING_SUMMARY_FILE}")
        phases["Mailing lists"] = time.time() - ml_t0
        if args.timestamp:
            stamp(f"Mail done in {_fmt_secs(phases['Mailing lists'])}")
    else:
        print("  skipping mailing list collection (--skip-mailing-lists)")

    # Phase 3: Per-project git/VCS activity collection
    if not args.skip_git:
        total = len(projects)
        collected = 0
        skipped = 0
        errors = 0
        vcs_t0 = time.time()
        git_times = project_times.setdefault("Git/VCS activity", {})
        if args.timestamp:
            stamp("Fetching VCS activity")
        for i, project in enumerate(projects, 1):
            if args.timestamp:
                stamp(project)
            status(f"[{i}/{total}] {project}: fetching git activity...")
            p_t0 = time.time()
            try:
                progress_str = f"[{i}/{total}] "
                git_stats = collect_git_activity(project, config, progress=progress_str)
                if git_stats and git_stats.get("totals", {}).get("commits", 0) > 0:
                    write_json(f"{project}_git", git_stats, config)
                    commits = git_stats["totals"]["commits"]
                    committers = git_stats["totals"]["committers"]
                    p_dt = time.time() - p_t0
                    msg = f"[{i}/{total}] {project}: {commits} commits, {committers} committers [{p_dt:.1f}s]"
                    # With --timestamp, keep each line so per-project times stay visible
                    (status_done if args.timestamp else status)(msg)
                    collected += 1
                else:
                    skipped += 1
                    p_dt = time.time() - p_t0
                    msg = f"[{i}/{total}] {project}: no git activity [{p_dt:.1f}s]"
                    (status_done if args.timestamp else status)(msg)
            except Exception as e:
                errors += 1
                p_dt = time.time() - p_t0
                status_done(f"  ✗ {project}: {e} [{p_dt:.1f}s]")
            git_times[project] = p_dt

            # Print budget every 20 projects
            if i % 20 == 0:
                rl = get_rate_limit_status()
                if rl["remaining"] is not None:
                    status_done(f"  [API budget: {rl['remaining']}/{rl['limit']} remaining, {rl['used']} calls used]")

        status_done(f"git activity: {collected} collected, {skipped} skipped, {errors} errors")
        # Show rate limit status
        rl = get_rate_limit_status()
        if rl["remaining"] is not None:
            print(f"  GitHub API budget: {rl['remaining']}/{rl['limit']} remaining "
                  f"({rl['used']} calls this session)")
        phases["Git/VCS activity"] = time.time() - vcs_t0
        if args.timestamp:
            stamp(f"VCS done in {_fmt_secs(phases['Git/VCS activity'])}")

    else:
        print("  skipping git/VCS collection (--skip-git)")

    if args.timestamp:
        stamp("Trends")

    # Phase 4: Compute activity trend classifications
    t0 = time.time()
    print("  computing activity trend classifications...")
    compute_activity_trends(config)
    phases["Activity trends"] = time.time() - t0

    if args.timestamp:
        total_secs = time.time() - run_t0
        stamp(f"Done in {_fmt_secs(total_secs)}")
        report_timings(phases, project_times, total_secs)

    print("\ndone.")


if __name__ == "__main__":
    main()

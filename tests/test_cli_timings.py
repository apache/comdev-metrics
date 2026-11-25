"""Tests for the --timestamp timing summary in cli.py (issue #11)."""

from asfmetrics.cli import _fmt_secs, report_timings


def test_fmt_secs():
    assert _fmt_secs(0) == "0s"
    assert _fmt_secs(45.4) == "45s"
    assert _fmt_secs(723) == "12m 03s"
    assert _fmt_secs(3909) == "1h 05m 09s"


def test_report_timings_ranks_slowest(capsys):
    phases = {"Mailing lists": 100.0, "Git/VCS activity": 300.0}
    project_times = {
        "Git/VCS activity": {"kafka": 200.0, "comdev": 10.0, "airflow": 90.0},
        "Mailing lists": {},
    }
    report_timings(phases, project_times, total=400.0, top_n=2)
    out = capsys.readouterr().out
    assert "Git/VCS activity" in out and "75.0%" in out
    git_section = out.split("Slowest 2 of 3 projects: Git/VCS activity")[1]
    assert git_section.index("kafka") < git_section.index("airflow")
    assert "comdev" not in git_section
    assert "projects: Mailing lists" not in out  # empty phase skipped


def test_report_timings_zero_total(capsys):
    report_timings({"Activity trends": 0.0}, {}, total=0.0)
    assert "0.0%" in capsys.readouterr().out

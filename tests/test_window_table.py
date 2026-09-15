"""The push-window table's durations are arithmetic, and arithmetic is checked here.

A typed window of 3h25m27s was reported as 25m27s on 2026-09-15, the hours dropped across
midnight UTC, and the recount that every session ran checked categories only, so it
could not have seen it. See tools/window_table.py. This runs the tool against the live
docs/status.md on every CI push and pins its failure modes on synthetic rows.
"""
from __future__ import annotations

from pathlib import Path

from tools import window_table as wt

REPO = Path(__file__).resolve().parent.parent

HEAD = "  | push | pushed (Z) | window opened by | window | landed inside | rebase |\n  | --- | --- | --- | --- | --- | --- |\n"


def _rows(*lines: str):
    return wt.parse(HEAD + "\n".join(lines) + "\n")


def test_live_table_parses_and_every_duration_matches_its_endpoints():
    rows = wt.parse((REPO / "docs" / "status.md").read_text(encoding="utf-8"))
    assert rows, "the row pattern matched nothing; an empty table is not a pass"
    problems, counts = wt.check(rows)
    assert problems == [], "\n".join(problems)
    assert counts["agree"] == counts["rows"]


def test_hours_dropped_across_midnight_fires():
    rows = _rows(
        "  | `aaaaaaa` | 09-14 20:59:39 | fresh clone at `bbbbbbb`, 20:50:00 | **9m39s** | — | no |",
        "  | `ccccccc` | 09-15 00:25:06 | prev push | **25m27s** | — | no |",
    )
    problems, _ = wt.check(rows)
    assert len(problems) == 1 and "3h25m27s" in problems[0]


def test_open_time_after_push_time_is_the_previous_day():
    rows = _rows("  | `aaaaaaa` | 09-15 00:05:00 | fresh clone at `bbbbbbb`, 23:55:00 | **10m00s** | — | no |")
    assert wt.check(rows)[0] == []


def test_stale_open_runs_from_the_previous_row():
    rows = _rows(
        "  | `aaaaaaa` | 09-08 18:38:14 | fresh clone at `bbbbbbb`, 18:30:00 | **8m14s** | — | no |",
        "  | `ccccccc` | 09-09 17:43:28 | STALE OPEN — prior session's last push | **23h05m14s** | `ddddddd` | **YES** |",
    )
    assert wt.check(rows)[0] == []


def test_an_open_with_no_written_start_fails():
    rows = _rows("  | `aaaaaaa` | 09-08 00:24:30 | fetch + FF onto `bbbbbbb` | **0m57s** | — | no |")
    problems, _ = wt.check(rows)
    assert len(problems) == 1 and "not derivable" in problems[0]


def test_one_second_is_tolerated_two_are_not():
    base = "  | `aaaaaaa` | 09-08 00:00:00 | fresh clone at `bbbbbbb`, 23:50:00 | **{}** | — | no |"
    assert wt.check(_rows(base.format("10m01s")))[0] == []
    assert len(wt.check(_rows(base.format("10m02s")))[0]) == 1


def test_prediction_band_is_read_off_the_recomputed_window():
    rows = _rows(
        "  | `4abdd83` | 09-10 20:13:18 | fresh clone at `bbbbbbb`, 17:00:00 | **3h13m18s** | — | no |",
        "  | `ccccccc` | 09-10 20:20:00 | prev push | **6m42s** | — | no |",
        "  | `ddddddd` | 09-11 00:00:00 | prev push | **3h40m00s** | `eeeeeee` | **YES** |",
    )
    problems, counts = wt.check(rows)
    assert problems == []
    assert [(s, reb) for s, _, reb in counts["qualifying"]] == [("4abdd83", False), ("ddddddd", True)]

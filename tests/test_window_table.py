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
    text = (REPO / "docs" / "status.md").read_text(encoding="utf-8")
    rows = wt.parse(text)
    assert rows, "the row pattern matched nothing; an empty table is not a pass"
    slots = wt.parse_slots(text)
    assert slots, "the slot pattern matched nothing; an empty slot table is not a pass"
    problems, counts = wt.check(rows, slots)
    assert problems == [], "\n".join(problems)
    assert counts["agree"] == counts["rows"]
    assert all(q["outcome"] is not None for q in counts["qualifying"])


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


SLOTS_HEAD = "  | slot (Z) | run | data commit | landed (Z) |\n  | --- | --- | --- | --- |\n"


def _slots(*lines: str):
    return wt.parse_slots(SLOTS_HEAD + "\n".join(lines) + "\n")


# Window 09-10 17:00:00 -> 20:13:18 meets only the 12:17 slot (range 14:22:29-17:54:52);
# 09-10 20:20:00 -> 09-11 00:00:00 meets only the 18:17 slot (range 20:22:29-23:54:52).
QUAL = (
    "  | `4abdd83` | 09-10 20:13:18 | fresh clone at `bbbbbbb`, 17:00:00 | **3h13m18s** | — | no |",
    "  | `ccccccc` | 09-10 20:20:00 | prev push | **6m42s** | — | no |",
    "  | `ddddddd` | 09-11 00:00:00 | prev push | **3h40m00s** | `eeeeeee` | **YES** |",
)


def test_prediction_band_is_read_off_the_recomputed_window():
    slots = _slots(
        "  | 09-10 12:17 | `1` | `aaaaaaa` | 09-10 16:35:29 |",
        "  | 09-10 18:17 | `2` | `bbbbbbb` | 09-10 21:03:53 |",
    )
    problems, counts = wt.check(_rows(*QUAL), slots)
    assert problems == []
    got = [(q["sha"], q["rebased"], q["outcome"]) for q in counts["qualifying"]]
    assert got == [("4abdd83", False, "missed"), ("ddddddd", True, "caught")]
    assert counts["outcomes"] == {"caught": 1, "missed": 1, "none": 0}
    assert counts["qualifying"][0]["into_band"] == "13m18s"


def test_slot_with_no_run_is_no_opportunity_not_a_miss():
    rows = _rows(QUAL[0])
    problems, counts = wt.check(rows, _slots("  | 09-10 12:17 | — | — | no run |"))
    assert problems == [] and counts["qualifying"][0]["outcome"] == "none"
    problems, counts = wt.check(rows, _slots("  | 09-10 12:17 | `1` | — | no commit |"))
    assert problems == [] and counts["qualifying"][0]["outcome"] == "none"


def test_qualifying_window_without_a_slot_row_refuses():
    problems, counts = wt.check(_rows(QUAL[0]), {})
    assert len(problems) == 1 and "cannot classify" in problems[0]
    assert counts["qualifying"][0]["outcome"] is None


def test_caught_must_agree_with_rebase():
    # a landing inside the window on a row that says no rebase
    problems, _ = wt.check(_rows(QUAL[0]), _slots("  | 09-10 12:17 | `1` | `aaaaaaa` | 09-10 17:10:00 |"))
    assert len(problems) == 1 and "classified caught but rebase no" in problems[0]

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
        "  | `aaaaaaa` | 09-14 20:59:39 | fresh clone at `bbbbbbb` (clone gone, not recoverable), 20:50:00 | **9m39s** | — | no |",
        "  | `ccccccc` | 09-15 00:25:06 | prev push | **25m27s** | — | no |",
    )
    problems, _ = wt.check(rows)
    assert len(problems) == 1 and "3h25m27s" in problems[0]


def test_open_time_after_push_time_is_the_previous_day():
    rows = _rows("  | `aaaaaaa` | 09-15 00:05:00 | fresh clone at `bbbbbbb` (clone gone, not recoverable), 23:55:00 | **10m00s** | — | no |")
    assert wt.check(rows)[0] == []


def test_stale_open_runs_from_the_previous_row():
    rows = _rows(
        "  | `aaaaaaa` | 09-08 18:38:14 | fresh clone at `bbbbbbb` (clone gone, not recoverable), 18:30:00 | **8m14s** | — | no |",
        "  | `ccccccc` | 09-09 17:43:28 | STALE OPEN — prior session's last push | **23h05m14s** | `ddddddd` | **YES** |",
    )
    assert wt.check(rows)[0] == []


def test_an_open_with_no_written_start_fails():
    rows = _rows("  | `aaaaaaa` | 09-08 00:24:30 | fetch + FF onto `bbbbbbb` | **0m57s** | — | no |")
    problems, _ = wt.check(rows)
    assert len(problems) == 1 and "not derivable" in problems[0]


def test_one_second_is_tolerated_two_are_not():
    base = "  | `aaaaaaa` | 09-08 00:00:00 | fresh clone at `bbbbbbb` (clone gone, not recoverable), 23:50:00 | **{}** | — | no |"
    assert wt.check(_rows(base.format("10m01s")))[0] == []
    assert len(wt.check(_rows(base.format("10m02s")))[0]) == 1


SLOTS_HEAD = "  | slot (Z) | run | data commit | landed (Z) |\n  | --- | --- | --- | --- |\n"


def _slots(*lines: str):
    return wt.parse_slots(SLOTS_HEAD + "\n".join(lines) + "\n")


# Window 09-10 17:00:00 -> 20:13:18 meets only the 12:17 slot's landing range, and
# 09-10 20:20:00 -> 09-11 00:00:00 only the 18:17 slot's, under docs/bands.yaml as it
# stood on 2026-09-15 (landing 2h11m48s to 6h02m14s, or 2h11m24s near once P2 closed).
QUAL = (
    "  | `4abdd83` | 09-10 20:13:18 | fresh clone at `bbbbbbb` (clone gone, not recoverable), 17:00:00 | **3h13m18s** | — | no |",
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


BANDS_YAML = """
fire:
  near: {{value: {fn}, n: 1, set_by: x, moved: 2026-01-01, bound: upper}}
  far: {{value: {ff}, n: 1, set_by: x, moved: 2026-01-01, bound: lower}}
commit_lag:
  near: {{value: {cn}, n: 1, set_by: x, moved: 2026-01-01, bound: upper}}
  far: {{value: {cf}, n: 1, set_by: x, moved: 2026-01-01, bound: lower}}
wall_clock:
  near: {{value: {wn}, n: 1, set_by: x, moved: 2026-01-01, bound: upper}}
  far: {{value: {wf}, n: 1, set_by: x, moved: 2026-01-01, bound: unsigned}}
"""


def _bands(tmp_path, fn="2h00m00s", ff="5h00m00s", cn="5m00s", cf="20m00s",
           wn="5m00s", wf="30m00s"):
    p = tmp_path / "bands.yaml"
    p.write_text(BANDS_YAML.format(fn=fn, ff=ff, cn=cn, cf=cf, wn=wn, wf=wf), encoding="utf-8")
    return wt.load_bands(p)


def test_landing_range_is_derived_from_the_declared_bands():
    # The live constants: derived, not typed.
    assert wt.LAND_NEAR == wt.FIRE_NEAR + wt.COMMIT_LAG_MIN
    assert wt.LAND_FAR == wt.FIRE_FAR + wt.COMMIT_LAG_MAX
    assert wt.LANDING == wt.load_bands().landing


def test_moving_a_declared_edge_moves_the_landing_range(tmp_path):
    base = _bands(tmp_path)
    assert wt._fmt(base.landing[0]) == "2h05m00s" and wt._fmt(base.landing[1]) == "5h20m00s"
    moved = _bands(tmp_path, cn="4m30s")
    assert wt._fmt(moved.landing[0]) == "2h04m30s"
    assert moved.landing[1] == base.landing[1]


def test_an_edge_without_provenance_is_refused(tmp_path):
    p = tmp_path / "bands.yaml"
    p.write_text(BANDS_YAML.format(fn="2h00m00s", ff="5h00m00s", cn="5m00s", cf="20m00s",
                                   wn="5m00s", wf="30m00s")
                 .replace(", set_by: x", "", 1), encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="set_by"):
        wt.load_bands(p)


def test_a_landing_between_the_two_near_edges_splits_the_ranges():
    # A commit recorded between the fire near edge and the landing near edge, placed off
    # the DECLARED bands so this test survives an edge moving. Read as a fire range, the
    # old behaviour, the slot meets the window and the commit is caught. Read as a
    # landing range, the slot cannot have landed yet: no opportunity.
    from datetime import datetime, timezone
    z = timezone.utc
    slot = datetime(2026, 9, 10, 12, 17, tzinfo=z)
    between = slot + wt.FIRE_NEAR + (wt.LAND_NEAR - wt.FIRE_NEAR) / 2
    between = between.replace(microsecond=0)
    start, end = slot + (wt.FIRE_NEAR / 2), between + (wt.LAND_NEAR - wt.FIRE_NEAR) / 4
    assert slot + wt.FIRE_NEAR < between < end < slot + wt.LAND_NEAR
    slots = _slots(f"  | 09-10 12:17 | `1` | `aaaaaaa` | {between:%m-%d %H:%M:%S} |")
    assert wt.classify(start, end, slots, wt.FIRE) == ("caught", [])
    assert wt.classify(start, end, slots, wt.LANDING) == ("none", [])
    assert wt.classify(start, end, slots) == ("none", []), "classification must default to the landing range"


def test_caught_must_agree_with_rebase():
    # a landing inside the window on a row that says no rebase
    problems, _ = wt.check(_rows(QUAL[0]), _slots("  | 09-10 12:17 | `1` | `aaaaaaa` | 09-10 17:10:00 |"))
    assert len(problems) == 1 and "classified caught but rebase no" in problems[0]


def test_an_open_time_must_name_the_instrument_that_produced_it():
    # Two reflogs answer "when did the fetch land" and disagree by tens of seconds --
    # 11m54s on `bdf4a6c`. The tool cannot tell them apart (a reflog is clone-local), so
    # what it enforces is that the row SAYS which one, and an untagged time is a failure
    # rather than a figure a later reader has to guess the provenance of.
    untagged = "  | `aaaaaaa` | 09-15 00:05:00 | fresh clone at `bbbbbbb`, 23:55:00 | **10m00s** | — | no |"
    problems, _ = wt.check(_rows(untagged))
    assert len(problems) == 1 and "names no instrument" in problems[0]

    tagged = untagged.replace("`bbbbbbb`,", "`bbbbbbb` (clone gone, not recoverable),")
    assert wt.check(_rows(tagged))[0] == []


# --- the concurrency thresholds, and the signing rule --------------------------------


def _fmt(td):
    return wt._fmt(td)


def test_thresholds_are_computed_at_the_declared_edges():
    # Four ranges, nothing between them: the two fire edges against the two wall-clock
    # extremes. These are the file's own numbers, so a moved edge moves this test -- which
    # is the point: the figures are DERIVED, and nothing may type them anywhere else.
    b = wt.load_bands()
    got = {(t["threshold"], t["edge"]): (_fmt(t["low"]), _fmt(t["high"])) for t in wt.thresholds(b)}
    assert got[("pending", "near")] == ("7h33m02s", "8h00m23s")
    assert got[("pending", "far")] == ("11h05m25s", "11h32m46s")
    assert got[("cancellation", "near")] == ("13h33m02s", "14h00m23s")
    assert got[("cancellation", "far")] == ("17h05m25s", "17h32m46s")
    # and each is the period plus the lag less the wall clock, not a typed constant
    assert got[("cancellation", "far")][1] == _fmt(
        wt.CANCEL_PERIOD + b.fire_far - b.wall_near
    )


def test_only_the_far_edge_high_end_is_signed():
    signs = {(t["threshold"], t["edge"]): (t["low_sign"], t["high_sign"])
             for t in wt.thresholds(wt.load_bands())}
    # low ends inherit wall_clock.far, which is unsigned; the near-row high end pairs
    # inputs that push opposite ways; only the far-row high end has both pushing low.
    assert signs[("pending", "near")] == (None, None)
    assert signs[("pending", "far")] == (None, "low")
    assert signs[("cancellation", "near")] == (None, None)
    assert signs[("cancellation", "far")] == (None, "low")


def test_the_counterfactual_signs_one_more_figure():
    # Computed, not asserted: remove the updatedAt limit, so the far wall-clock edge is
    # an ordinary lower bound on a true maximum. The near-row low end becomes signed
    # high; nothing else moves; one more figure is signed than in the file as declared.
    b = wt.load_bands()
    bounds = dict(b.bounds, **{"wall_clock.far": "lower"})
    signs = {(t["threshold"], t["edge"]): (t["low_sign"], t["high_sign"])
             for t in wt.thresholds(b, bounds)}
    assert signs[("pending", "near")] == ("high", None)
    assert signs[("pending", "far")] == (None, "low")
    declared = sum(1 for t in wt.thresholds(b) for k in ("low_sign", "high_sign") if t[k])
    counter = sum(1 for t in wt.thresholds(b, bounds) for k in ("low_sign", "high_sign") if t[k])
    assert counter == declared + 2, "one more figure signed on each of the two thresholds"


def test_flipping_a_declared_direction_moves_the_signs_as_the_rule_predicts():
    # THE MUTATION TEST, run from a baseline the two tests above assert green. Each flip
    # is one edge's declared direction; the expected pair is worked from the rule -- a
    # positive term carries its direction through, the subtracted term flips it -- and
    # not from the implementation.
    b = wt.load_bands()

    def signs(**over):
        bounds = dict(b.bounds, **over)
        return {(t["threshold"], t["edge"]): (t["low_sign"], t["high_sign"])
                for t in wt.thresholds(b, bounds)}

    # fire.near becomes a lower bound: the near-row high end now has both inputs low.
    assert signs(**{"fire.near": "lower"})[("pending", "near")] == (None, "low")
    # fire.far becomes an upper bound: the far-row high end loses its sign.
    assert signs(**{"fire.far": "upper"})[("pending", "far")] == (None, None)
    # wall_clock.near becomes a lower bound: subtracting an understatement reads high,
    # so the near-row high end signs high and the far-row high end loses its sign.
    flipped = signs(**{"wall_clock.near": "lower"})
    assert flipped[("pending", "near")] == (None, "high")
    assert flipped[("pending", "far")] == (None, None)
    # wall_clock.far becomes an upper bound: the far-row low end signs low.
    assert signs(**{"wall_clock.far": "upper"})[("pending", "far")] == ("low", "low")


def test_a_missing_or_bad_bound_is_a_refusal(tmp_path):
    # The directions are DECLARED. A file without them cannot be signed, and the loader
    # says so rather than defaulting to a direction nobody wrote down.
    src = (REPO / "docs" / "bands.yaml").read_text(encoding="utf-8")
    # the FIELD, not the header sentence that names it: both lines carry the string
    kept = [ln for ln in src.splitlines(True) if not ln.startswith("    bound: unsigned")]
    assert len(kept) == len(src.splitlines(True)) - 1
    broken = tmp_path / "bands.yaml"
    broken.write_text("".join(kept), encoding="utf-8")
    try:
        wt.load_bands(broken)
    except ValueError as e:
        assert "bound" in str(e)
    else:
        raise AssertionError("a missing `bound` must refuse")

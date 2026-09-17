"""`web/lib/staleness.ts`'s constants must agree with the files they were copied from.

WHY A COPY EXISTS AT ALL. `docs/bands.yaml` is the one place a band edge is written, and
`tools/window_table.py` derives `heartbeat_far` from it and types it nowhere. No route in
the read layer reads YAML, so the page carries the derived figure as a literal -- and a
literal copied out of a moving file is exactly the shape this repo has been bitten by
before. The same pattern guards the other constants the web layer duplicates
(`test_court_alias_agreement`, `test_presidential_types_agreement`): assert the two
sources against each other, in a test that fails when one of them moves.

WHAT WOULD HAPPEN WITHOUT IT. `wall_clock.far` is the least stable edge in the file --
declared 2026-09-16, unsignable, and sitting on a band the file itself says is not
converging. When it moves, `heartbeat_far` moves with it, the page keeps comparing
against yesterday's edge, and nothing anywhere goes red: the element would simply call a
healthy late run missed, or stop calling a missed one missed, with every test green.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools import window_table as wt  # noqa: E402

STALENESS = REPO / "web" / "lib" / "staleness.ts"


def _ts_number(name: str) -> int:
    """The declared value of a `export const NAME = <expr>;` line, evaluated as the
    arithmetic it is written as -- so the test reads what the file says rather than a
    number someone also wrote in a comment."""
    src = STALENESS.read_text(encoding="utf-8")
    m = re.search(r"export const " + name + r"\s*=\s*([^;]+);", src)
    assert m, f"{name} is not declared in {STALENESS.name}"
    expr = m.group(1).split("//")[0].strip()
    assert re.fullmatch(r"[\d_\s*+()\-]+", expr), f"{name} is not plain arithmetic: {expr!r}"
    return int(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 -- shape asserted above


def test_heartbeat_far_agrees_with_the_derived_band():
    """The join. `heartbeat_far` is derived from docs/bands.yaml and typed nowhere in
    Python; the page's literal must equal it to the millisecond."""
    derived = wt.load_bands().heartbeat_far
    assert _ts_number("HEARTBEAT_FAR_MS") == int(derived.total_seconds() * 1000)


def test_the_page_uses_heartbeat_far_and_not_landing_far():
    """THE SPECIFIC WRONG NUMBER, named so the test fails for a readable reason.

    `landing_far` measures when a data commit lands, mid-run; `heartbeat_far` measures
    when the run ends. They differ by 8s today and the record holds a run -- 34755670262,
    the 09-13 06:17Z slot -- whose run-end sits between them, so a page wired to
    landing_far would have called a healthy run missed.
    """
    bands = wt.load_bands()
    assert bands.heartbeat_far != bands.landing[1], (
        "the two far edges have converged; this test can no longer tell them apart"
    )
    assert _ts_number("HEARTBEAT_FAR_MS") != int(bands.landing[1].total_seconds() * 1000)


def test_the_slots_agree_with_the_cron_table():
    src = STALENESS.read_text(encoding="utf-8")
    hours = re.search(r"export const SLOT_HOURS = \[([^\]]+)\]", src)
    assert hours, "SLOT_HOURS is not declared"
    assert [int(x) for x in hours.group(1).split(",")] == list(wt.SLOT_HOURS)
    assert _ts_number("SLOT_MINUTE") == wt.SLOT_MINUTE

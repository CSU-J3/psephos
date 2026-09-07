"""The alias set is written twice, in two languages. This is what keeps them equal.

`collectors/tracker_uw.py` maps UW's spelling to a CourtListener id, so the collector
can resolve the docket. `web/lib/court.ts` maps the same spelling to the court's NAME,
so the page can display it and `isCircuit` can classify it. Both are needed and neither
can be derived from the other: an id is not a name.

That makes them a pair that can drift, and drift here is silent in the worst way. Add a
third UW spelling to the Python side only and the row resolves and polls -- while the
page renders the tracker's typo and, if the typo omits the word "circuit", draws a
venue-refile glyph on a circuit appeal. Add it to the TypeScript side only and the page
reads correctly about a row the collector never fetched.

So: THE KEY SETS MUST BE EQUAL, and this fails in either direction.

It lives on the Python side because the Python map is the one a person edits. The
signal that a new alias is needed is `tracker_uw`'s own WARN on an unmapped court, and
whoever answers that WARN is editing COURT_IDS -- so the test that fires should be in
the suite covering the file they have open.

The TS side is read by parsing, which is the cost of the choice. The parse is pinned to
the exact literal form and asserts what it found, so a rewrite of court.ts that this
regex cannot read fails the test rather than silently matching nothing -- the failure
mode that makes a green cross-language check worthless.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from collectors import tracker_uw as t

COURT_TS = Path(__file__).resolve().parent.parent / "web" / "lib" / "court.ts"


def _ts_aliases() -> dict[str, str]:
    """Parse COURT_ALIASES out of web/lib/court.ts."""
    src = COURT_TS.read_text(encoding="utf-8")
    m = re.search(
        r"export const COURT_ALIASES: Record<string, string> = \{(.*?)\n\};",
        src, re.S,
    )
    assert m, f"COURT_ALIASES literal not found in {COURT_TS} -- has its form changed?"
    body = m.group(1)
    pairs = re.findall(r'"([^"]+)":\s*"([^"]+)",', body)
    # Every non-blank line in the literal must have parsed. A regex that quietly matches
    # a subset would make this whole test pass for the wrong reason.
    lines = [ln for ln in body.split("\n") if ln.strip() and not ln.strip().startswith("//")]
    assert len(pairs) == len(lines), (
        f"parsed {len(pairs)} pair(s) from {len(lines)} line(s) of the TS literal; "
        f"the parse is incomplete, not the map"
    )
    return dict(pairs)


def test_alias_key_sets_agree_in_both_directions():
    py = set(t.COURT_ALIASES)
    ts = set(_ts_aliases())
    assert py == ts, (
        f"alias sets have drifted.\n"
        f"  only in collectors/tracker_uw.py COURT_ALIASES: {sorted(py - ts)}\n"
        f"  only in web/lib/court.ts COURT_ALIASES:         {sorted(ts - py)}\n"
        f"Both are required: the Python side resolves the docket, the TS side displays "
        f"and classifies it."
    )


def test_each_alias_targets_the_same_court_on_both_sides():
    """Stronger than key equality, and this is the half that catches a transposition.

    Equal keys with swapped values -- 'Eighth District' -> cadc, 'DC Circuit' -> ca8 --
    passes the test above, resolves to a real docket, and renders a real court name.
    Nothing downstream could catch it. Here the TS value (a court NAME) is looked up in
    COURT_IDS and must yield the SAME id the Python alias gives.
    """
    ts = _ts_aliases()
    for spelling, court_id in t.COURT_ALIASES.items():
        name = ts[spelling]
        assert name in t.COURT_IDS, (
            f"web/lib/court.ts maps {spelling!r} -> {name!r}, which is not a court name "
            f"in COURT_IDS -- the display name must be a court this project knows"
        )
        assert t.COURT_IDS[name] == court_id, (
            f"{spelling!r} points at two different courts: tracker_uw gives "
            f"{court_id!r}, court.ts gives {name!r} which is {t.COURT_IDS[name]!r}"
        )


def test_an_alias_is_never_also_a_real_court_name():
    """An alias key that is itself a canonical name would make canonicalCourt rewrite a
    correct string, and would mean COURT_IDS's closed set had gained a duplicate."""
    ts = _ts_aliases()
    for spelling, name in ts.items():
        assert spelling != name, f"{spelling!r} aliases to itself"
    # And the target of every alias is a fixed point: canonicalizing it changes nothing.
    for name in ts.values():
        assert name not in ts, (
            f"{name!r} is both an alias target and an alias key -- canonicalCourt would "
            f"need two passes, and it makes exactly one"
        )


def test_the_two_known_aliases_are_present():
    """The pair this unit exists for, pinned by value on both sides.

    Not redundant with the agreement tests: those keep the sides EQUAL, and two equal
    sides can both be wrong. These are the values read off the UW artifact and verified
    against CourtListener on 2026-09-06.
    """
    assert t.COURT_ALIASES["Eighth District"] == "ca8"
    assert t.COURT_ALIASES["DC Circuit"] == "cadc"
    ts = _ts_aliases()
    assert ts["Eighth District"] == "Eighth Circuit"
    assert ts["DC Circuit"] == "D.C. Circuit"


def test_divergence_is_actually_detected():
    """The test above passes today. This proves it would FAIL tomorrow.

    A cross-language agreement check that has never been seen red is an assumption, not
    a guard -- and the parse is the part most likely to fail open.
    """
    ts = _ts_aliases()
    assert set(ts) == set(t.COURT_ALIASES)          # the real state
    drifted = dict(ts)
    drifted.pop("DC Circuit")
    assert set(drifted) != set(t.COURT_ALIASES)     # a dropped TS key is caught
    drifted = dict(ts)
    drifted["Fifth District"] = "Fifth Circuit"
    assert set(drifted) != set(t.COURT_ALIASES)     # an added TS key is caught
    # And the parse is not vacuously empty, which would make every set comparison above
    # trivially true.
    assert len(ts) >= 2, f"parsed only {len(ts)} alias(es) from court.ts"

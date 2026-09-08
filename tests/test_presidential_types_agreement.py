"""Tab 3's spine sentence names the collector's document types. This keeps them equal.

`collectors/executive.py` holds `PRESIDENTIAL_TYPES` as Federal Register query values.
`web/lib/stands.ts` holds the same list as prose, and the "Where this stands" section
renders it: *"queries the Federal Register for all seven presidential document types --
determination, executive order, ... -- and the configured election terms decide
relevance"*.

THIS IS THE EXACT CLAIM THAT WENT STALE ONCE ALREADY. The section mock's earlier spine
read "the collector requests executive orders only". That was true when it was drawn
and false two days later, when `da49c3f` widened the query to all seven types -- and it
stayed on the page for twelve more days. A sentence describing a file ages exactly like
a comment describing a file, and nothing was checking it.

So the requirement the unit-D handoff set: a type added to the collector must BREAK THE
BUILD until the sentence follows. That is what this test does, in both directions.

It lives on the Python side, with the same reasoning as
`tests/test_court_alias_agreement.py`: the Python list is the one a person edits. Adding
a document type is a collector change, and the test that fires should be in the suite
covering the file they have open.

THE TWO LISTS ARE NOT BYTE-EQUAL AND SHOULD NOT BE. Federal Register query values use
underscores (`executive_order`); English prose does not (`executive order`). The
normalisation below is the only difference this test tolerates, and it is applied to
both sides rather than to one.

The TS side is read by parsing, which is the cost of the choice. The parse is pinned to
the exact literal form and asserts what it found, so a rewrite of stands.ts this regex
cannot read fails the test rather than silently matching nothing -- the failure mode
that makes a green cross-language check worthless.
"""
from __future__ import annotations

import re
from pathlib import Path

from collectors import executive as e

STANDS_TS = Path(__file__).resolve().parent.parent / "web" / "lib" / "stands.ts"


def _normalise(name: str) -> str:
    """One vocabulary for two spellings of the same type."""
    return name.replace("_", " ").strip().lower()


def _ts_types() -> list[str]:
    """Parse PRESIDENTIAL_TYPES out of web/lib/stands.ts."""
    src = STANDS_TS.read_text(encoding="utf-8")
    m = re.search(
        r"export const PRESIDENTIAL_TYPES: readonly string\[\] = \[(.*?)\n\];",
        src, re.S,
    )
    assert m, f"PRESIDENTIAL_TYPES literal not found in {STANDS_TS} -- has its form changed?"
    body = m.group(1)
    found = re.findall(r'"([^"]+)",', body)
    # Every non-blank, non-comment line in the literal must have parsed. A regex that
    # quietly matched a subset would make this whole test pass for the wrong reason.
    lines = [ln for ln in body.split("\n") if ln.strip() and not ln.strip().startswith("//")]
    assert len(found) == len(lines), (
        f"parsed {len(found)} value(s) from {len(lines)} line(s) of the TS literal; "
        f"the parse is incomplete, not the list"
    )
    return found


def test_type_sets_agree_in_both_directions():
    py = {_normalise(t) for t in e.PRESIDENTIAL_TYPES}
    ts = {_normalise(t) for t in _ts_types()}
    assert py == ts, (
        "collectors/executive.py PRESIDENTIAL_TYPES and web/lib/stands.ts have drifted.\n"
        f"  only in the collector: {sorted(py - ts)}\n"
        f"  only in the page:      {sorted(ts - py)}\n"
        "A type added to the collector must be named in tab 3's spine sentence too, or "
        "the page describes a query the collector no longer makes."
    )


def test_the_sentence_says_seven_and_there_are_seven():
    """The prose hard-codes a count word. It has to match the list it introduces."""
    assert len(e.PRESIDENTIAL_TYPES) == 7, (
        f"the section says 'all seven presidential document types' and the collector now "
        f"requests {len(e.PRESIDENTIAL_TYPES)}. Update the sentence in "
        f"web/components/WhereThisStands.tsx as well as the two lists."
    )
    component = (
        Path(__file__).resolve().parent.parent / "web" / "components" / "WhereThisStands.tsx"
    ).read_text(encoding="utf-8")
    assert "all seven presidential document types" in component, (
        "the spine sentence in WhereThisStands.tsx no longer reads 'all seven presidential "
        "document types' -- if the wording changed deliberately, update this assertion; if "
        "the COUNT changed, this test is telling you the sentence and the list disagree"
    )


def test_the_lists_are_in_the_same_order():
    """Not required for correctness, but the page renders the TS order and a reader
    comparing the two files should not have to sort them mentally."""
    assert [_normalise(t) for t in e.PRESIDENTIAL_TYPES] == [
        _normalise(t) for t in _ts_types()
    ]

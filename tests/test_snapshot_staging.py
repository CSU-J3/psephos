"""The export's snapshot paths must agree with what collect.yml actually commits.

WHY THIS EXISTS. `collect.yml` stages the snapshots BY NAME -- deliberately, because
`git add data/` would start committing `data/psephos.db`, which is not gitignored.
The cost of that choice is a silent failure mode, and the workflow's own comment has
named it since the line was written:

    Every new snapshot must be added here by name or it is written each run
    and never committed -- silent, since the export prints it either way.

That warning was correct, was sitting three lines above the defect, and did not
prevent it. `data/generated_at.json` was added to `export/snapshots.py` and not to
the `git add` line, so every cron rewrote it and no cron committed it. The tracked
copy stayed frozen at a hand-seeded 2026-09-07 while the database moved on.

It was not cosmetic in either direction it reached:

  - `web/scripts/assert-gates.mjs` compares every authored claim's `recheck_after`
    against that file, deliberately rather than against the wall clock. A frozen
    clock cannot pass a date, so NO CLAIM CAN EVER EXPIRE -- the check built to catch
    "a claim nobody revisited" was disarmed, silently, and would have stayed green
    through 2026-09-16, the date `eo-blocked-per-reporting` was written to red on.
  - The shipped section's as-of chip reads that same figure, so the live site told
    readers the record was collected on Sep 7 for as long as it went uncommitted.

A PROSE WARNING CANNOT FAIL. This is the same warning, joined to the file it warns
about, in a form that does.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

SNAPSHOTS = REPO / "export" / "snapshots.py"
COLLECT_YML = REPO / ".github" / "workflows" / "collect.yml"

# Written by collectors/tracker_uw.py (ARTIFACT_PATH), not by the export, so it is
# legitimately staged without appearing among the export's constants. Named here so
# the reverse direction can still fail: an unexplained path in the add list is a
# path nobody joined to a writer.
EXTERNAL_ARTIFACTS = {"data/doj_cases.json"}


def _exported_paths() -> set[str]:
    """Every module-level `*_PATH = "data/...json"` in the export.

    Parsed rather than grepped: a constant is an assignment, and `ast` reads the
    file the way Python does instead of the way a regex hopes it looks."""
    tree = ast.parse(SNAPSHOTS.read_text(encoding="utf-8"))
    out = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name) or not target.id.endswith("_PATH"):
                continue
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                out.add(node.value.value)
    return out


def _staged_paths() -> set[str]:
    """The paths on collect.yml's `git add` line."""
    text = COLLECT_YML.read_text(encoding="utf-8")
    lines = [l.strip() for l in text.splitlines() if l.strip().startswith("git add ")]
    assert len(lines) == 1, f"expected exactly one `git add` line, found {len(lines)}"
    return set(lines[0][len("git add "):].split())


def test_every_exported_snapshot_is_staged_by_the_cron():
    """The defect's own direction: a path the export writes and the commit forgets
    is invisible, because the export prints it either way."""
    exported = _exported_paths()
    assert exported, "parsed no *_PATH constants -- the parser, not the export, is wrong"
    missing = exported - _staged_paths()
    assert not missing, (
        f"export/snapshots.py writes {sorted(missing)} but .github/workflows/collect.yml "
        f"never stages it, so every cron rewrites it and none commits it. Add it to the "
        f"`git add` line."
    )


def test_every_staged_path_has_a_writer():
    """The other direction, so the join cannot be satisfied by staging everything.
    A staged path is either one the export writes or a named external artifact."""
    unexplained = _staged_paths() - _exported_paths() - EXTERNAL_ARTIFACTS
    assert not unexplained, (
        f"collect.yml stages {sorted(unexplained)}, which no export constant produces "
        f"and EXTERNAL_ARTIFACTS does not name. Either it is dead, or its writer needs "
        f"recording here."
    )


def test_the_generated_at_clock_is_among_them():
    """Named explicitly, not left to the join. This is the path whose absence froze
    the gate register's clock and the page's as-of chip; a refactor that dropped it
    from the export would otherwise satisfy both tests above by symmetry."""
    assert "data/generated_at.json" in _exported_paths()
    assert "data/generated_at.json" in _staged_paths()

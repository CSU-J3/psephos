"""collect.yml's four slot lines and its slot label must stay what the labelled era needs.

WHY THIS EXISTS. Until 2026-09-14 collect.yml ran on one line, `17 */6 * * *`, and
every run was assigned to a slot by counting one run per slot. Counting carried a
premise nobody stated, and an empty six-hour interval made its neighbours
unassignable (docs/status.md, the falsified entry on counting). The fix split the
line into one cron line per slot, so `github.event.schedule` names the slot that
fired, and wrote that string into the run-name and the data commit subject.

Both halves fail SILENTLY, which is why they are asserted here rather than trusted:

  - A DROPPED CRON LINE is a dead slot. Nothing goes red; the slot simply never
    fires, and in the run record it reads as an empty interval -- the one thing the
    labelled era exists to end.
  - A MALFORMED LABEL EXPRESSION renders empty rather than failing. The run-name
    goes blank, the subject loses its slot, and every run is green.

What this cannot check is the rendered value; that is the P2 read in docs/status.md,
off `gh run list --json displayTitle`. This checks that the file still asks for it.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
COLLECT_YML = REPO / ".github" / "workflows" / "collect.yml"

# A word boundary, not a substring: `github.event.schedulee` contains the substring,
# and actionlint cannot flag it either, because `github.event` is an untyped object.
SCHEDULE = re.compile(r"\$\{\{\s*github\.event\.schedule(?![A-Za-z0-9_])")

SLOTS = {"17 0 * * *", "17 6 * * *", "17 12 * * *", "17 18 * * *"}


def _workflow() -> dict:
    return yaml.safe_load(COLLECT_YML.read_text(encoding="utf-8"))


def _on(wf: dict) -> dict:
    # PyYAML is YAML 1.1: a bare `on:` key loads as the boolean True, not "on".
    return wf.get("on", wf.get(True))


def _commit_step(wf: dict) -> dict:
    steps = wf["jobs"]["collect"]["steps"]
    matches = [s for s in steps if s.get("name") == "Commit data changes"]
    assert len(matches) == 1, f"expected one 'Commit data changes' step, found {len(matches)}"
    return matches[0]


def test_exactly_four_cron_lines_one_per_slot():
    crons = [entry["cron"] for entry in _on(_workflow())["schedule"]]
    assert len(crons) == 4, f"expected 4 cron lines, found {len(crons)}: {crons}"
    assert set(crons) == SLOTS, f"cron lines {sorted(crons)} are not the four slots {sorted(SLOTS)}"


def test_run_name_carries_the_schedule():
    run_name = _workflow().get("run-name")
    assert run_name, "collect.yml has no run-name; runs would not name their slot"
    assert SCHEDULE.search(run_name), f"run-name does not read github.event.schedule: {run_name!r}"


def test_commit_step_defines_the_slot_and_uses_it():
    step = _commit_step(_workflow())
    slot = (step.get("env") or {}).get("SLOT")
    assert slot, "the commit step defines no SLOT env var"
    assert SCHEDULE.search(slot), f"SLOT does not read github.event.schedule: {slot!r}"
    assert "$SLOT" in step["run"], "the commit step defines SLOT but its script never uses it"

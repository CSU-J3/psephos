"""Recompute docs/status.md's push-window table from its own endpoints.

WHY THIS EXISTS. The window table under *Standing invariants* carries, per push, when
it was pushed, what opened its window, the window's length, what landed inside it and
whether it rebased. Every session recounted it with an inline snippet that checked the
CATEGORIES -- opens against follow-ons, landings against rebases -- and never the
ARITHMETIC. So a typed duration could be wrong and pass, and it was: on 2026-09-15 a
window of 3h25m27s (20:59:39Z to 00:25:06Z, across midnight UTC) was reported as
25m27s, exactly the hours dropped. The frozen prediction's 3h-to-6h band is read off
that very figure, so a wrong duration silently moves a push in or out of the test.

WHAT IT CHECKS, per row:
  - the window's start comes from the row itself: the previous row's push time for a
    `prev push` or a `STALE OPEN` (whose window runs from the prior session's last push,
    which is the previous row), and the `, HH:MM:SS` time written in the opened-by cell
    for a fetch or a fresh clone. A time later than the push is the previous UTC day.
  - the typed duration must equal push minus start to within one second.
  - landed-inside and rebase must agree (a landing iff YES), the model the table asserts.
A row whose start cannot be derived from the row is itself a failure: an endpoint that
is not written down cannot be checked.

It reports the counts the status page quotes and the frozen prediction's tally, both
COUNTED from the table on every run rather than carried forward. Exit 0 clean, 1 on any
mismatch. Read-only; lives in tools/ for that reason.

THE TALLY HAS THREE OUTCOMES, NOT TWO (2026-09-15). A qualifying window with no landing
available in it is not a test of the window model, so each qualifying sample is
classified by what could have landed in it:
  - caught   -- a slot's run landed a data commit inside the window;
  - missed   -- slots whose landing ranges meet the window ran and committed, but every
                landing fell outside it;
  - none     -- no slot's landing range meets the window, or every slot that does
                produced no run or no data commit.
A slot's landing range is the slot plus the counted-era spread, 2h05m29s to 5h37m52s
(`collect.yml`). Which slots meet a window is COMPUTED here. What each slot's run did is
not in this repo's data -- it is the run record -- so it is READ once and written into
the slot table beside the window table; this tool requires a row for every slot that
meets a qualifying window and refuses to classify without one. A `caught` sample whose
row says no rebase, or a rebased sample that is not `caught`, is a mismatch.

    python -m tools.window_table [--doc docs/status.md]
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
YEAR = 2026

ROW = re.compile(
    r"^\s*\| `(?P<sha>[0-9a-f]{7})` \| (?P<pushed>\d\d-\d\d \d\d:\d\d:\d\d) \| (?P<opened>.*?) \| "
    r"\*\*(?P<window>[^*]+)\*\* \| (?P<landed>.*?) \| (?P<rebase>.*?) \|\s*$"
)
DURATION = re.compile(r"^(?:(?P<h>\d+)h)?(?P<m>\d+)m(?P<s>\d\d)s$")
OPEN_TIME = re.compile(r", (?P<t>\d\d:\d\d:\d\d)$")

# The prediction, restated 2026-09-10: of the next four pushes whose window falls
# between 3h and 6h, at least one meets a rebase. It counts from 4abdd83, the first
# push after the restatement.
PREDICTION_FROM = "4abdd83"
BAND_LO = timedelta(hours=3)
BAND_HI = timedelta(hours=6)
PREDICTION_N = 4

SLOT_HOURS = (0, 6, 12, 18)
SLOT_MINUTE = 17
LAND_NEAR = timedelta(hours=2, minutes=5, seconds=29)
LAND_FAR = timedelta(hours=5, minutes=37, seconds=52)

SLOT_ROW = re.compile(
    r"^\s*\| (?P<slot>\d\d-\d\d (?:00|06|12|18):17) \| (?P<run>`\d+`|—) \| (?P<commit>`[0-9a-f]{7}`|—) \| "
    r"(?P<landed>\d\d-\d\d \d\d:\d\d:\d\d|no run|no commit) \|\s*$"
)


@dataclass
class Row:
    sha: str
    pushed: datetime
    opened: str
    typed: str
    landed: str
    rebased: bool

    @property
    def follow_on(self) -> bool:
        return self.opened == "prev push"


def _ts(mmdd_hms: str) -> datetime:
    return datetime.strptime(f"{YEAR}-{mmdd_hms}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _dur(text: str) -> timedelta | None:
    m = DURATION.match(text.strip())
    if not m:
        return None
    return timedelta(hours=int(m["h"] or 0), minutes=int(m["m"]), seconds=int(m["s"]))


def _fmt(td: timedelta) -> str:
    total = int(td.total_seconds())
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


def parse(text: str) -> list[Row]:
    rows = []
    for line in text.splitlines():
        m = ROW.match(line)
        if m:
            rows.append(Row(
                sha=m["sha"],
                pushed=_ts(m["pushed"]),
                opened=m["opened"].strip(),
                typed=m["window"].strip(),
                landed=m["landed"].strip(),
                rebased="YES" in m["rebase"],
            ))
    return rows


def parse_slots(text: str) -> dict[datetime, datetime | None]:
    """Slot time -> landing time of its data commit, or None for no run / no commit."""
    out: dict[datetime, datetime | None] = {}
    for line in text.splitlines():
        m = SLOT_ROW.match(line)
        if m:
            slot = _ts(m["slot"] + ":00")
            out[slot] = _ts(m["landed"]) if m["landed"][0].isdigit() else None
    return out


def slots_meeting(start: datetime, end: datetime) -> list[datetime]:
    """Every slot whose landing range [slot+NEAR, slot+FAR] overlaps [start, end]."""
    found = []
    day = (start - LAND_FAR).date()
    while True:
        for h in SLOT_HOURS:
            slot = datetime(day.year, day.month, day.day, h, SLOT_MINUTE, tzinfo=timezone.utc)
            if slot + LAND_NEAR > end:
                return found
            if slot + LAND_FAR >= start:
                found.append(slot)
        day = day + timedelta(days=1)


def classify(start: datetime, end: datetime, slots: dict) -> tuple[str | None, list[str]]:
    """caught / missed / none for one qualifying window, or (None, missing slots)."""
    meeting = slots_meeting(start, end)
    missing = [f"{s:%m-%d %H:%M}" for s in meeting if s not in slots]
    if missing:
        return None, missing
    landings = [slots[s] for s in meeting if slots[s] is not None]
    if any(start <= t <= end for t in landings):
        return "caught", []
    if landings:
        return "missed", []
    return "none", []


def window_start(rows: list[Row], i: int) -> datetime | None:
    row = rows[i]
    if row.follow_on or row.opened.startswith("STALE OPEN"):
        return rows[i - 1].pushed if i > 0 else None
    m = OPEN_TIME.search(row.opened)
    if not m:
        return None
    t = datetime.strptime(m["t"], "%H:%M:%S").time()
    start = datetime.combine(row.pushed.date(), t, tzinfo=timezone.utc)
    return start - timedelta(days=1) if start > row.pushed else start


def check(rows: list[Row], slots: dict | None = None) -> tuple[list[str], dict]:
    slots = slots or {}
    problems: list[str] = []
    windows: dict[str, timedelta] = {}
    starts: dict[str, datetime] = {}
    for i, row in enumerate(rows):
        start = window_start(rows, i)
        typed = _dur(row.typed)
        if start is None:
            problems.append(f"{row.sha}: window start not derivable from the row (opened by: {row.opened!r})")
            continue
        if typed is None:
            problems.append(f"{row.sha}: typed window {row.typed!r} is not a duration")
            continue
        actual = row.pushed - start
        windows[row.sha] = actual
        starts[row.sha] = start
        if abs((actual - typed).total_seconds()) > 1:
            problems.append(
                f"{row.sha}: typed {row.typed}, endpoints give {_fmt(actual)} "
                f"({start:%m-%d %H:%M:%S} -> {row.pushed:%m-%d %H:%M:%S})"
            )
        if (row.landed != "—") != row.rebased:
            problems.append(f"{row.sha}: landed {row.landed!r} but rebase {'YES' if row.rebased else 'no'}")

    follow = [r for r in rows if r.follow_on]
    shas = [r.sha for r in rows]
    tally = []
    if PREDICTION_FROM in shas:
        for r in rows[shas.index(PREDICTION_FROM):]:
            w = windows.get(r.sha)
            if w is not None and BAND_LO <= w <= BAND_HI:
                tally.append(r)
    qualifying = []
    for r in tally[:PREDICTION_N]:
        w = windows[r.sha]
        outcome, missing = classify(starts[r.sha], r.pushed, slots)
        if outcome is None:
            problems.append(f"{r.sha}: qualifying, but no slot-table row for {', '.join(missing)}; cannot classify")
        elif (outcome == "caught") != r.rebased:
            problems.append(f"{r.sha}: classified {outcome} but rebase {'YES' if r.rebased else 'no'}")
        qualifying.append({
            "sha": r.sha,
            "window": _fmt(w),
            "into_band": _fmt(w - BAND_LO),
            "band_pct": 100 * (w - BAND_LO) / (BAND_HI - BAND_LO),
            "rebased": r.rebased,
            "outcome": outcome,
            "slots": [f"{s:%m-%d %H:%M}" for s in slots_meeting(starts[r.sha], r.pushed)],
        })
    counts = {
        "rows": len(rows),
        "opens": len(rows) - len(follow),
        "follow_ons": len(follow),
        "equal": sum(1 for r in follow if not r.rebased),
        "follow_on_rebased": sum(1 for r in follow if r.rebased),
        "agree": sum(1 for r in rows if (r.landed != "—") == r.rebased),
        "qualifying": qualifying,
        "outcomes": {k: sum(1 for q in qualifying if q["outcome"] == k) for k in ("caught", "missed", "none")},
    }
    return problems, counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", default=str(REPO / "docs" / "status.md"))
    args = ap.parse_args(argv)
    text = Path(args.doc).read_text(encoding="utf-8")
    rows = parse(text)
    if not rows:
        print("no window table rows found -- the pattern matched nothing, which is not a pass")
        return 1
    problems, c = check(rows, parse_slots(text))
    print(f"rows {c['rows']}, opens {c['opens']}, follow-ons {c['follow_ons']}, "
          f"equal {c['equal']}, follow-ons rebased {c['follow_on_rebased']}, "
          f"model agrees {c['agree']} of {c['rows']}")
    q, o = c["qualifying"], c["outcomes"]
    print(f"prediction (from {PREDICTION_FROM}, windows 3h-6h, first {PREDICTION_N}): {len(q)} of {PREDICTION_N} read -- "
          f"opportunity caught {o['caught']}, opportunity missed {o['missed']}, no opportunity present {o['none']}")
    for s in q:
        print(f"  {s['sha']} window {s['window']}, {s['into_band']} into the band ({s['band_pct']:.1f}%), "
              f"{'rebased' if s['rebased'] else 'no rebase'}, slots meeting it: {', '.join(s['slots']) or 'none'} "
              f"-> {s['outcome'] or 'UNCLASSIFIED'}")
    for p in problems:
        print("MISMATCH", p)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())

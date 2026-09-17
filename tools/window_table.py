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
    A row that writes a time must also NAME the instrument it came from, in
    parentheses: the two reflogs that could have supplied it disagree by tens of
    seconds and this tool cannot tell them apart.
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
TWO RANGES, AND THEY ANSWER DIFFERENT QUESTIONS (split 2026-09-15). The FIRE range is
the slot plus the observed spread of run_started_at: when a slot's run STARTS, which
answers whether a slot ran, or is absent rather than late. The LANDING range is the fire
range plus the commit-lag band: when a data commit can land. A window meets a rebase only
by a COMMIT landing in it, so opportunity is classified on the LANDING range. Until the
split this tool, and the record, used the fire range as a landing window, early by the
commit-lag band's two edges. Every edge is declared in docs/bands.yaml and none is
written here. Which slots meet a window is COMPUTED here. What each
slot's run did is not in this repo's data -- it is the run record -- so it is READ once
and written into
the slot table beside the window table; this tool requires a row for every slot that
meets a qualifying window and refuses to classify without one. A `caught` sample whose
row says no rebase, or a rebased sample that is not `caught`, is a mismatch.

    python -m tools.window_table [--doc docs/status.md]
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
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

# A WRITTEN OPEN TIME NAMES THE INSTRUMENT THAT PRODUCED IT, from 2026-09-16. Two
# reflogs answer "when did the fetch land", and they disagree: the LOCAL branch's
# `merge origin/main: Fast-forward` against `origin/main`'s `fetch origin:
# fast-forward`: 5s apart on `dd3af8c`, 23s on `222a4d3`, 35s on `a558c8b` and
# 11m54s on `bdf4a6c`, which is thirteen times that row's own window. All four rows
# were written from the branch reflog, and nothing in the row said so -- so
# the next session had a coin to flip, and a window typed from the other one would be
# INTERNALLY CONSISTENT and pass every check below. This tool cannot tell them apart:
# a reflog is clone-local and dies with the clone (the five 09-13 fresh-clone rows are
# already unrecoverable for exactly that reason). So it enforces the one thing it can --
# that the row DECLARES its source -- and the declaration is what a later reader audits
# against, rather than re-deriving a figure whose instrument nobody wrote down.
OPEN_SOURCES = ("branch reflog", "remote reflog", "clone gone, not recoverable")

# The prediction, restated 2026-09-10: of the next four pushes whose window falls
# between 3h and 6h, at least one meets a rebase. It counts from 4abdd83, the first
# push after the restatement.
PREDICTION_FROM = "4abdd83"
BAND_LO = timedelta(hours=3)
BAND_HI = timedelta(hours=6)
PREDICTION_N = 4

SLOT_HOURS = (0, 6, 12, 18)
SLOT_MINUTE = 17
# THE BAND EDGES ARE NOT WRITTEN HERE. They are declared once, in docs/bands.yaml, each
# with its sample count, what set it and when it last moved, and read at import. The
# landing range is derived from them and typed nowhere. Moving an edge is an edit to that
# file and never to this one.
BANDS_PATH = REPO / "docs" / "bands.yaml"


@dataclass(frozen=True)
class Bands:
    fire_near: timedelta
    fire_far: timedelta
    commit_near: timedelta
    commit_far: timedelta
    wall_near: timedelta
    wall_far: timedelta
    # Each edge's declared direction of error, keyed "band.end": "upper" (the observed
    # value sits at or above the true one), "lower" (at or below), or "unsigned" (the
    # file cannot say -- wall_clock.far, where sampling and the updatedAt lag push
    # opposite ways). Read from the file, never assumed here.
    bounds: dict = field(default_factory=dict)

    @property
    def fire(self) -> tuple[timedelta, timedelta]:
        return (self.fire_near, self.fire_far)

    @property
    def landing(self) -> tuple[timedelta, timedelta]:
        # Derived, never declared: near = fire near + commit near, far = fire far + commit far.
        return (self.fire_near + self.commit_near, self.fire_far + self.commit_far)


def load_bands(path: Path = BANDS_PATH) -> Bands:
    import yaml

    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    def edge(band: str, end: str) -> timedelta:
        raw = str(doc[band][end]["value"])
        m = DURATION.match(raw.strip())
        if not m:
            raise ValueError(f"{path}: {band}.{end}.value {raw!r} is not a duration")
        for field in ("n", "set_by", "moved"):
            if field not in doc[band][end]:
                raise ValueError(f"{path}: {band}.{end} carries no {field!r}")
        return timedelta(hours=int(m["h"] or 0), minutes=int(m["m"]), seconds=int(m["s"]))

    def bound(band: str, end: str) -> str:
        v = doc[band][end].get("bound")
        if v not in ("upper", "lower", "unsigned"):
            raise ValueError(
                f"{path}: {band}.{end} carries no usable `bound` "
                f"(upper / lower / unsigned), got {v!r}"
            )
        return v

    b = Bands(
        edge("fire", "near"), edge("fire", "far"),
        edge("commit_lag", "near"), edge("commit_lag", "far"),
        edge("wall_clock", "near"), edge("wall_clock", "far"),
        {f"{band}.{end}": bound(band, end)
         for band in ("fire", "commit_lag", "wall_clock") for end in ("near", "far")},
    )
    if not (b.fire_near < b.fire_far and b.commit_near < b.commit_far
            and b.wall_near < b.wall_far):
        raise ValueError(f"{path}: a band's near edge is not below its far edge")
    return b


# --- the concurrency thresholds, computed and signed ---------------------------------
#
# WHAT A THRESHOLD IS. `collect.yml` fires every 6h. A run that is still going when the
# next one is DISPATCHED makes that next run wait pending; a run still going when the
# one after it is dispatched makes GitHub cancel. Both are a race between one run's wall
# clock and the NEXT run's own lag, so the formulas are:
#
#     pending      = 6h  + the next run's lag   - the earlier run's wall clock
#     cancellation = 12h + the third run's lag  - the earlier run's wall clock
#
# PRICED AT THE DECLARED EDGES ONLY, four ranges and nothing between them: the two fire
# edges against the two wall-clock extremes. The middle is unpriced on purpose -- see
# the closing comment in docs/bands.yaml for why a median has no place in that file.
PENDING_PERIOD = timedelta(hours=6)
CANCEL_PERIOD = timedelta(hours=12)

# SIGNING IS COMPUTED, NOT TYPED. A term entering POSITIVELY (the lag) carries its own
# direction through: an upper bound makes the result read high, a lower bound low. The
# SUBTRACTED term (the wall clock) flips both, because subtracting an overstatement
# leaves the result low. A figure is signed only when both contributions agree; an
# `unsigned` input makes its figure unsigned whatever the other input says.
_PLUS = {"upper": "high", "lower": "low", "unsigned": None}
_MINUS = {"upper": "low", "lower": "high", "unsigned": None}


def sign(plus_bound: str, minus_bound: str) -> str | None:
    a, b = _PLUS[plus_bound], _MINUS[minus_bound]
    return a if a is not None and a == b else None


def thresholds(bands: Bands, bounds: dict | None = None) -> list[dict]:
    """The four ranges, each with the sign of each end. Pure: no I/O, no printing."""
    bd = bounds if bounds is not None else bands.bounds
    out = []
    for name, period in (("pending", PENDING_PERIOD), ("cancellation", CANCEL_PERIOD)):
        for end, lag in (("near", bands.fire_near), ("far", bands.fire_far)):
            out.append({
                "threshold": name,
                "edge": end,
                # low end: the biggest wall clock eats the most of the period
                "low": period + lag - bands.wall_far,
                "high": period + lag - bands.wall_near,
                "low_sign": sign(bd[f"fire.{end}"], bd["wall_clock.far"]),
                "high_sign": sign(bd[f"fire.{end}"], bd["wall_clock.near"]),
            })
    return out


BANDS = load_bands()
FIRE_NEAR, FIRE_FAR = BANDS.fire
COMMIT_LAG_MIN, COMMIT_LAG_MAX = BANDS.commit_near, BANDS.commit_far
LAND_NEAR, LAND_FAR = BANDS.landing
FIRE = BANDS.fire
LANDING = BANDS.landing

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

    @property
    def kind(self) -> str:
        """Which of the four window shapes opened this row, per the status page.

        The tally is split on this because the shapes are not interchangeable
        evidence. Every stale open in the table before `e4f6ea6` ran 15h55m to
        23h05m and spanned three or four landings, so none of them ever reached
        the 3h-6h band -- the mixing this guards against had never once been
        possible. It became possible on the first SHORT stale open, and a
        category that rebases whenever it appears would be counted as evidence
        about windows in general if the split were only in prose."""
        if self.follow_on:
            return "prev push"
        if self.opened.startswith("STALE OPEN"):
            return "stale open"
        if "clone" in self.opened:
            return "fresh clone"
        return "fetch"


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


def slots_meeting(start: datetime, end: datetime, rng: tuple[timedelta, timedelta] = LANDING) -> list[datetime]:
    """Every slot whose range [slot+near, slot+far] overlaps [start, end].

    `rng` defaults to the LANDING range, the one opportunity is about. Pass FIRE to ask
    whose runs could have STARTED inside the window instead."""
    near, far = rng
    found = []
    day = (start - far).date()
    while True:
        for h in SLOT_HOURS:
            slot = datetime(day.year, day.month, day.day, h, SLOT_MINUTE, tzinfo=timezone.utc)
            if slot + near > end:
                return found
            if slot + far >= start:
                found.append(slot)
        day = day + timedelta(days=1)


def classify(start: datetime, end: datetime, slots: dict,
             rng: tuple[timedelta, timedelta] = LANDING
             ) -> tuple[str | None, list[str], datetime | None]:
    """caught / missed / none for one qualifying window, or (None, missing slots).

    The third value is WHERE the catch landed, returned so the caller can price it:
    a landing in the first minutes of a long window is a catch the window barely
    had to be open for, and `caught` alone cannot say so."""
    meeting = slots_meeting(start, end, rng)
    missing = [f"{s:%m-%d %H:%M}" for s in meeting if s not in slots]
    if missing:
        return None, missing, None
    landings = [slots[s] for s in meeting if slots[s] is not None]
    inside = [t for t in landings if start <= t <= end]
    if inside:
        return "caught", [], min(inside)
    if landings:
        return "missed", [], None
    return "none", [], None


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


def check(rows: list[Row], slots: dict | None = None,
          landing: tuple[timedelta, timedelta] = LANDING) -> tuple[list[str], dict]:
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
        if OPEN_TIME.search(row.opened) and not any(
            f"({src})" in row.opened for src in OPEN_SOURCES
        ):
            problems.append(
                f"{row.sha}: the open time names no instrument -- add one of "
                + ", ".join(f"({src})" for src in OPEN_SOURCES)
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
        outcome, missing, at = classify(starts[r.sha], r.pushed, slots, landing)
        if outcome is None:
            problems.append(f"{r.sha}: qualifying, but no slot-table row for {', '.join(missing)}; cannot classify")
        elif (outcome == "caught") != r.rebased:
            problems.append(f"{r.sha}: classified {outcome} but rebase {'YES' if r.rebased else 'no'}")
        entry = {
            "sha": r.sha,
            "kind": r.kind,
            "window": _fmt(w),
            "into_band": _fmt(w - BAND_LO),
            "band_pct": 100 * (w - BAND_LO) / (BAND_HI - BAND_LO),
            "rebased": r.rebased,
            "outcome": outcome,
            "slots": [f"{s:%m-%d %H:%M}" for s in slots_meeting(starts[r.sha], r.pushed, landing)],
            "landing_at": at,
            "landing_into": None,
            "landing_pct": None,
        }
        if at is not None:
            into = at - starts[r.sha]
            entry["landing_into"] = _fmt(into)
            entry["landing_pct"] = 100 * into / w
        qualifying.append(entry)
    counts = {
        "rows": len(rows),
        "opens": len(rows) - len(follow),
        "follow_ons": len(follow),
        "equal": sum(1 for r in follow if not r.rebased),
        "follow_on_rebased": sum(1 for r in follow if r.rebased),
        "agree": sum(1 for r in rows if (r.landed != "—") == r.rebased),
        "qualifying": qualifying,
        "outcomes": {k: sum(1 for q in qualifying if q["outcome"] == k) for k in ("caught", "missed", "none")},
        # Split on window kind as well as totalled, because the shapes are not
        # interchangeable evidence. See Row.kind.
        "outcomes_by_kind": {
            kind: {k: sum(1 for q in qualifying
                          if q["kind"] == kind and q["outcome"] == k)
                   for k in ("caught", "missed", "none")}
            for kind in sorted({q["kind"] for q in qualifying})
        },
    }
    return problems, counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", default=str(REPO / "docs" / "status.md"))
    ap.add_argument("--bands", default=str(BANDS_PATH))
    args = ap.parse_args(argv)
    text = Path(args.doc).read_text(encoding="utf-8")
    rows = parse(text)
    if not rows:
        print("no window table rows found -- the pattern matched nothing, which is not a pass")
        return 1
    bands = load_bands(Path(args.bands))
    print(f"bands ({args.bands}): fire {_fmt(bands.fire[0])} to {_fmt(bands.fire[1])}, "
          f"commit lag {_fmt(bands.commit_near)} to {_fmt(bands.commit_far)}, "
          f"landing (derived) {_fmt(bands.landing[0])} to {_fmt(bands.landing[1])}")
    print(f"wall clock {_fmt(bands.wall_near)} to {_fmt(bands.wall_far)} "
          f"(bounds: {bands.bounds['wall_clock.near']}/{bands.bounds['wall_clock.far']})")
    print("concurrency thresholds (computed at the declared edges; the middle is unpriced)")
    for t in thresholds(bands):
        print(f"  {t['threshold']:<12} {t['edge']:<4} fire edge: "
              f"{_fmt(t['low'])} [{t['low_sign'] or 'unsigned'}] to "
              f"{_fmt(t['high'])} [{t['high_sign'] or 'unsigned'}]")
    problems, c = check(rows, parse_slots(text), bands.landing)
    print(f"rows {c['rows']}, opens {c['opens']}, follow-ons {c['follow_ons']}, "
          f"equal {c['equal']}, follow-ons rebased {c['follow_on_rebased']}, "
          f"model agrees {c['agree']} of {c['rows']}")
    q, o = c["qualifying"], c["outcomes"]
    print(f"prediction (from {PREDICTION_FROM}, windows 3h-6h, first {PREDICTION_N}): {len(q)} of {PREDICTION_N} read -- "
          f"opportunity caught {o['caught']}, opportunity missed {o['missed']}, no opportunity present {o['none']}")
    for kind, o2 in c["outcomes_by_kind"].items():
        n = o2["caught"] + o2["missed"] + o2["none"]
        print(f"  by window kind -- {kind}: caught {o2['caught']}, missed {o2['missed']}, "
              f"no opportunity {o2['none']} (n={n})")
    for s in q:
        print(f"  {s['sha']} [{s['kind']}] window {s['window']}, {s['into_band']} into the band "
              f"({s['band_pct']:.1f}%), {'rebased' if s['rebased'] else 'no rebase'}, "
              f"slots meeting it: {', '.join(s['slots']) or 'none'} -> {s['outcome'] or 'UNCLASSIFIED'}")
        if s["landing_at"] is not None:
            print(f"      landing {s['landing_at']:%m-%d %H:%M:%S}Z, {s['landing_into']} into the window "
                  f"({s['landing_pct']:.1f}% of it)")
    for p in problems:
        print("MISMATCH", p)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())

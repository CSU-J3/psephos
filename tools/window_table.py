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


def check(rows: list[Row]) -> tuple[list[str], dict]:
    problems: list[str] = []
    windows: dict[str, timedelta] = {}
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
    counts = {
        "rows": len(rows),
        "opens": len(rows) - len(follow),
        "follow_ons": len(follow),
        "equal": sum(1 for r in follow if not r.rebased),
        "follow_on_rebased": sum(1 for r in follow if r.rebased),
        "agree": sum(1 for r in rows if (r.landed != "—") == r.rebased),
        "qualifying": [(r.sha, _fmt(windows[r.sha]), r.rebased) for r in tally[:PREDICTION_N]],
    }
    return problems, counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", default=str(REPO / "docs" / "status.md"))
    args = ap.parse_args(argv)
    rows = parse(Path(args.doc).read_text(encoding="utf-8"))
    if not rows:
        print("no window table rows found -- the pattern matched nothing, which is not a pass")
        return 1
    problems, c = check(rows)
    print(f"rows {c['rows']}, opens {c['opens']}, follow-ons {c['follow_ons']}, "
          f"equal {c['equal']}, follow-ons rebased {c['follow_on_rebased']}, "
          f"model agrees {c['agree']} of {c['rows']}")
    q = c["qualifying"]
    hits = sum(1 for _, _, reb in q if reb)
    print(f"prediction (from {PREDICTION_FROM}, windows 3h-6h, first {PREDICTION_N}): "
          f"{len(q)} of {PREDICTION_N} read, {hits} met a rebase: "
          + (", ".join(f"{s} {w} {'rebased' if reb else 'no rebase'}" for s, w, reb in q) or "none"))
    for p in problems:
        print("MISMATCH", p)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())

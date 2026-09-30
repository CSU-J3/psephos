"""The tier-2 rule: two CourtListener objects that describe one minute entry (R1, Corey
2026-09-30, ruling 3).

No upstream field links them. The D0 sampled three pairs (71499795, Jul 18, Jul 20, Sep 29):
distinct entry ids, distinct document ids, and a consistent fingerprint -- the short object
carries a time_filed and takes its text from its document, the full-text object does not.
One docket-report load enriches a numbered entry in place and creates a second object for
the minute order. So the link is psephos's assertion, made by this rule or by a person,
named in `cl_entries.twin_rule`, and reversible (scripts/link_entry_twins.py).

THE RULE IS THE D0'S STRICT-B, ported from dup_d0/work2_ab/ident.py and kept to it so the
256 same-run pairs Corey ruled on are the pairs it makes. On one docket and one day:
  * short -> long: a text of 60 characters or fewer (recheck_flags.is_short) and a longer
    one, both order-headed or both not (recheck_flags.HEAD), every content word of the short
    present in the long on a 5-letter stem -- or, with no content words, the head alone
    ('type_only');
  * long twins: two longer texts equal, or one a prefix of the other (40+ characters),
    once stamps and clerk annotations are stripped;
an edge must touch a text with no document URL (a tokened pair is tier 1, one object), and
it is kept only when unique at both ends. Pairs the D0 found in the SAME collector run are
what the rule links; the rest go to a person.

It reads recheck_flags' pinned helpers rather than copying them: the flag test is frozen
until the measurement period ends (2026-11-12), and one definition is what keeps this rule
and the D0's figures the same rule.
"""

from __future__ import annotations

import bisect
import collections
import re
from datetime import datetime

import tools.recheck_flags as rf

RULE = "same-run strict-B v1"

_STAMP_ANY = re.compile(r"[\(\[]\s*Entered:\s*[^\)\]]*[\)\]]", re.I)
_CLERK = re.compile(r"\*{3}\s*filed in error\s*\*{3}|this entry has been removed from the docket\.?|"
                    r"\[?-*\[?edited[^\]]*\]|modified on [0-9/]+[^)]*|clerk'?s note:[^.]*\.", re.I)
_STOP2 = set(rf._STOP) | {"motion", "util", "set", "reset", "deadlines", "deadline", "and",
                          "not", "with", "entry"}
RUN_GAP_SECONDS = 1800   # items more than 30 minutes apart belong to different runs


def ntext(s: str | None) -> str:
    s = rf.norm(s)
    s = _STAMP_ANY.sub(" ", s)
    s = _CLERK.sub(" ", s)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s.lower()).split())


def ordhead(s: str | None) -> bool:
    return bool(rf.HEAD.match(rf.norm(s).lstrip(".~- ").strip()))


def _words(s: str | None) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", (s or "").lower()) if w not in _STOP2 and len(w) > 2]


def _stems(s: str | None) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-z]+", (s or "").lower())}


def edges_for_day(rows: list[dict]) -> list[tuple[int, int, str]]:
    """Every strict-B edge among one docket-day's texts, before the tokenless and
    uniqueness filters. rows: dicts with id and description. (short id, long id, kind)."""
    out = []
    shorts = [r for r in rows if rf.is_short(r["description"])]
    longs = [r for r in rows if not rf.is_short(r["description"])]
    for s in shorts:
        w = _words(s["description"])
        for lg in longs:
            if ordhead(s["description"]) != ordhead(lg["description"]):
                continue
            st = _stems(lg["description"])
            if not w:
                out.append((s["id"], lg["id"], "type_only"))
            elif all(x[:5] in st for x in w):
                out.append((s["id"], lg["id"], "short_long"))
    for i, a in enumerate(longs):
        na = ntext(a["description"])
        for b in longs[i + 1:]:
            nb = ntext(b["description"])
            if na == nb:
                out.append((a["id"], b["id"], "long_twin_eq"))
            elif min(len(na), len(nb)) >= 40 and (na.startswith(nb) or nb.startswith(na)):
                out.append((a["id"], b["id"], "long_twin_prefix"))
    return out


def strict_b(rows: list[dict]) -> tuple[list[tuple[int, int, str]], list[int]]:
    """The rule over rows (id, case_id, entry_at, description, document_url, and
    cl_entry_id when known): the edges it keeps, and the short rows it leaves ambiguous
    (a candidate twin, but not unique).

    UNIQUENESS IS BY ENTRY, not by row. Two rows of one CourtListener object are one entry
    re-described (tier 1), so they are never an edge, and they are not two rival partners:
    a ruled pair must not drop out of the rule because one side later gained a revision
    row (a FILED IN ERROR on the long form, say). A row no object claims is its own entry,
    which is every row on the D0's dump -- so on it this is the D0's rule exactly: 279
    edges."""
    days = collections.defaultdict(list)
    for r in rows:
        days[(r["case_id"], r["entry_at"])].append(r)
    tokenless = {r["id"] for r in rows if not r.get("document_url")}
    ent = {r["id"]: (r.get("cl_entry_id") if r.get("cl_entry_id") is not None else ("row", r["id"]))
           for r in rows}
    t2 = [e for day in days.values() for e in edges_for_day(day)
          if (e[0] in tokenless or e[1] in tokenless) and ent[e[0]] != ent[e[1]]]
    partners: dict = collections.defaultdict(set)
    for a, b, _ in t2:
        partners[ent[a]].add(ent[b])
        partners[ent[b]].add(ent[a])
    by_pair: dict = {}
    for a, b, k in t2:
        if len(partners[ent[a]]) == 1 and len(partners[ent[b]]) == 1:
            key = frozenset((ent[a], ent[b]))
            # One edge per pair of entries; a short-form edge first, so the short side is
            # known (link_entry_twins._root), then the lowest row ids.
            rank = (k not in ("short_long", "type_only"), min(a, b), max(a, b))
            if key not in by_pair or rank < by_pair[key][0]:
                by_pair[key] = (rank, (a, b, k))
    kept = sorted(e for _, e in by_pair.values())
    amb = sorted({a for a, b, k in t2 if k in ("short_long", "type_only")}
                 - {a for a, b, k in kept if k in ("short_long", "type_only")})
    return kept, amb


# --------------------------------------------------------------------------- #
# Same run: the id bracket (dup_d0/work2_ab/runs.py)
# --------------------------------------------------------------------------- #
def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class RunClock:
    """Which collector run held a row. Runs are clusters of items.fetched_at split on gaps
    over 30 minutes; a row with an item is in its item's run, and any other row lies
    between the runs of its nearest item-bearing neighbours by id (case_entries ids are
    one AUTOINCREMENT, written in run order)."""

    def __init__(self, fetched: list[str], item_row_times: dict[int, str]):
        ts = sorted(_ts(f) for f in fetched)
        self.starts = [ts[0]] if ts else []
        self.ends = []
        for a, b in zip(ts, ts[1:]):
            if (b - a).total_seconds() > RUN_GAP_SECONDS:
                self.ends.append(a)
                self.starts.append(b)
        if ts:
            self.ends.append(ts[-1])
        self.ib = sorted(item_row_times)
        self.ib_run = {i: self.run_of(_ts(item_row_times[i])) for i in self.ib}

    def run_of(self, t: datetime) -> int:
        return bisect.bisect_right(self.starts, t) - 1

    def bracket(self, rid: int) -> tuple[int, int]:
        if rid in self.ib_run:
            return self.ib_run[rid], self.ib_run[rid]
        k = bisect.bisect_left(self.ib, rid)
        lo = self.ib_run[self.ib[k - 1]] if k > 0 else 0
        hi = self.ib_run[self.ib[k]] if k < len(self.ib) else len(self.starts) - 1
        return lo, hi

    def relation(self, a: int, b: int) -> str:
        la, ha = self.bracket(a)
        lb, hb = self.bracket(b)
        if la == ha == lb == hb:
            return "same-run"
        if ha < lb or hb < la:
            return "cross-run"
        return "undetermined"

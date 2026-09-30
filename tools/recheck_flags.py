"""Recheck flags: order-like docket entries on a watched docket -- one a gate lists, above
its last reading, or one cleared by a no-claim-order reason, filed after its read-through
date. Read-only. Writes nothing to the database
and nothing to the register.

    python -m tools.recheck_flags                          # the report, as section 9 prints it
    python -m tools.recheck_flags --fragment               # a reading's YAML, per listed docket
    python -m tools.recheck_flags --comment-body F --posted P   # audit.yml's flag comment

RULED 2026-09-29 (Corey), on the D0 of that day (docs/status.md, *The SAVE-system stay
READ ...*, ruling (3)). An authored gate lists, in `record_instruments`, the held dockets
its falsifier names. Each listed docket carries a READING in the gate's `record_read`: the
day a person read it against the claim and `through_entry_id`, MAX(case_entries.id) held
at that reading. A FLAG is an entry above that watermark whose text is order-like by the
test below. A flag is a prompt to read, never a verdict: this module decides nothing about
what an order means, and it never turns a run red.

AN ID WATERMARK, NOT A DATE. `entry_at` is a filing date with no time, RECAP backfills
late (the D0 measured at least 56 of 219 window rows arriving two or more days after
their `entry_at`), and ids do not follow dates even within a docket. The id is the one
column that orders arrivals.

THE TEST (the D0's V4, ported verbatim from its measured prototype):
  - NORMALISE: strip the docket-system prefixes before the document type ("[11318591] ",
    "ECF FILER:", "***DOCUMENT LOCKED***", "Judge X: "); a removed or entered-in-error
    row never flags.
  - HEAD: the text BEGINS with an order-type head -- an optional qualifier, then
    order(s)/ordered/opinion/judgment/mandate; or "notice of [interlocutory|cross]
    appeal"; or "per curiam". A docket entry names its own document type first.
  - TRIM: an order head whose text names a procedural subject (pro hac vice, extension,
    briefing schedule, amicus, seal, transcript, scheduling ...) is dropped, unless a
    protected operative term also appears (injunct, enjoin, stay, dismiss, judgment,
    vacat, remand, certiorari, en banc, consolidat, transfer, mandate, affirm, revers
    ...). A notice of appeal is never trimmed.
  - DISPO: a disposition reported in a non-order entry also flags -- "application for
    stay was granted" in a Supreme Court clerk's letter, a certiorari petition docketed.
  - SHORT FORMS: a description of 60 characters or fewer ("Order filed") takes the
    verdict of its long-form twin; with no twin it stays flagged and is marked
    UNREADABLE, its content being only in the PDF.
On the D0's window (2026-09-15..09-28, 251 rows) it flags 15, 8 true, 7 false, 0 missed;
the naive test, Corey's five words anywhere, flags 51 with 1 missed. The naive count is
reported beside the test's so the gap stays visible.

ITS LIMITS, STATED (the D0): tuned in-sample by the reader who labelled the rows; recall
proven on D.D.C., D. Mass. and First Circuit forms only. "MEMORANDUM DECISION AND ORDER",
"TEMPORARY RESTRAINING ORDER", the Ninth Circuit's "FILED ORDER"/"FILED OPINION", the
Second Circuit's "SUMMARY ORDER" and "AMENDED NOTICE OF APPEAL" do not match. RULED (Corey,
2026-09-29): the Ninth Circuit's and other courts' forms are added and re-tested before
ANY EO 14248 docket seeds, whatever its court; the forms above are the D0's note of what
is known not to match, not the boundary of the rule. The collector's own `is_substantive`
matches substrings ("recorder", "border") and is not reused here.

WHAT IT WATCHES. Every docket a gate lists, from its reading's id watermark. And, since
Corey's ruling of 2026-09-29, every docket that passes assert-gates check 5 by a
NO-CLAIM-ORDER reason, from that reason's `read_through` date: the date works as its
watermark, so an order-like entry FILED after it flags as a listed docket's would, and the
flag says the reason needs re-ruling. (A date, not an id, as ruled: such a docket has no
reading to carry an id. An entry filed on or before the date but ingested later does not
flag.) A consolidated member is watched only through its listed lead.

THE VERDICT CLASSES (ruled 2026-09-29): operative (a flag that bears on a claim, "true");
noise (a flag that does not, "false"); missed (an operative entry the test did not flag);
duplicate (the same order or notice held as a second row -- one docket entry under its
short and its full description, the later row of the pair -- its own class, not false);
unread (open until its text is read: the report lists every unread verdict whatever the
watermark, and the fragment re-offers it). A no-claim-order docket's verdicts ride on its
reason, `gate_coverage.verdicts` on the seed, since it has no reading. The test stays pinned during the
measurement; the duplicate count is evidence for its revision at the period's end.

THE MEASUREMENT. Every flag gets a verdict at its recheck -- operative or noise -- and
the reader skims the unflagged entries since the watermark and records any operative one
as missed; the verdicts ride on the reading (`record_read[].verdicts`) and ACCUMULATE: a
moved reading keeps every verdict its docket has had, so the tally is the period's, not
the latest interval's (review of this build, 2026-09-29). The bar for an
alarm, ruled, and not yet in force: no missed operative order across the period and at
most a third of flags false, the period running to at least 2026-11-12 and 30 verdicts.
Until then this is a report line (coverage_audit section 9) and a standing-issue comment.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
GATES_PATH = ROOT / "docs" / "gates.yaml"

VERDICTS = ("operative", "noise", "missed", "duplicate", "unread")
SLOT = "operative | noise | duplicate | unread"   # a fragment's placeholder, to be edited
READING_KEYS = {"docket", "read_on", "through_entry_id", "through_entry_at", "verdicts"}
# The ruled bar, restated where the report prints it.
PERIOD_END = "2026-11-12"
VERDICTS_NEEDED = 30
COURTLISTENER_DOCKET = "https://www.courtlistener.com/docket/{}/"
MARKER = re.compile(r"<!--\s*recheck-flags:\s*([\d,\s]*)-->")

# --------------------------------------------------------------------------- #
# The order-like test (the D0's V4; scratchpad d0gate/flags.py, measured 2026-09-29)
# --------------------------------------------------------------------------- #
_LEAD = re.compile(
    r"^\s*(?:\[\d+\]\s*)+"                       # 10th Cir: "[11318591] "
    r"|^\s*ECF FILER:\s*"                         # 3d Cir
    r"|^\s*\*{3}DOCUMENT LOCKED\*{3}\s*"          # 8th Cir
    r"|^\s*(?:Magistrate\s+)?Judge\s+[^:]{2,60}:\s*",  # D. Mass.: "Judge X: "
    re.I,
)
_REMOVED = re.compile(r"^\s*(?:This entry has been removed from the docket|ENTERED IN ERROR)", re.I)

# The naive test, Corey's five words anywhere: reported beside the real one, never used.
NAIVE = re.compile(r"\b(?:orders?|ordered|opinions?|judgments?|mandate|notice\s+of\s+appeal)\b", re.I)

HEAD = re.compile(
    r"""^(?:
        (?:(?:minute|electronic|text(?:[-\s]only)?|oral|paperless|scheduling|briefing|
             court|clerk'?s?|motion|so|final|amended|usca|
             memorandum(?:\s*(?:and|&))?|per\s+curiam)\s+)?
        (?:orders?|ordered|opinion|judgment|mandate)\b
      | notice\s+of\s+(?:interlocutory\s+|cross[-\s]?)?appeal\b
      | per\s+curiam\b
    )""",
    re.I | re.X,
)
NOA_HEAD = re.compile(r"^notice\s+of\s+(?:interlocutory\s+|cross[-\s]?)?appeal\b", re.I)
PROCEDURAL = re.compile(
    r"pro\s+hac\s+vice|\bappear(?:ance)?s?\b|leave\s+to\s+appear|\bwithdraw"
    r"|\bextension\b|extend(?:ing|ed)?\s+(?:the\s+)?(?:time|deadline)|enlarge"
    r"|briefing\s+(?:schedule|order)|accepted\s+for\s+filing|\bis\s+accepted\b"
    r"|separate\s+(?:appellee\s+)?briefs?|paper\s+copies|\bamicus\b|\bamici\b"
    r"|excess\s+pages|additional\s+pages|leave\s+to\s+file|\bexpedite"
    r"|standing\s+order|personal\s+devices|\bseal(?:ed|ing)?\b|transcript|mediation"
    r"|\bhearing\s+(?:set|reset|scheduled|continued)|status\s+(?:report|conference)"
    r"|set/reset|deadlines?\b|\bscheduling\b|clarification|intervene|intervention|reassign"
    r"|establishing\s+procedures|meet\s+and\s+confer|double-spaced",
    re.I,
)
PROTECT = re.compile(
    r"injunct|enjoin|restraining|\bstay(?:s|ed|ing)?\b|dismiss|judgment|vacat|remand"
    r"|certiorari|rehearing|en\s+banc|consolidat|\btransfer|merits|mandate|affirm|revers"
    r"|summary\s+disposition|declar(?:ed|atory)|\bvoid\b|contempt",
    re.I,
)
DISPO = re.compile(
    r"""\b(?:application|motion|request|petition)s?\s+(?:for\s+(?:an?\s+)?)?
          (?:(?:administrative|emergency)\s+)?
          (?:stay|writ\s+of\s+certiorari|certiorari|rehearing(?:\s+en\s+banc)?|injunction)\b
          [^.;]{0,80}?\b(?:is\s+|was\s+|are\s+|were\s+|has\s+been\s+)?(?:granted|denied|dismissed|vacated)\b
      | \bcertiorari\b[^.;]{0,80}?\b(?:filed|docketed|granted|denied)\b
      | \bpetition\s+for\s+(?:a\s+)?writ\s+of\s+certiorari\b
      | \bsupreme\s+court\b[^.;]{0,160}?\b(?:granted|denied|docketed)\b
    """,
    re.I | re.X,
)
SHORT = 60  # a description this short is a PACER short form, e.g. "Order filed"
_STOP = {"order", "on", "for", "to", "and", "the", "of", "filed", "court", "a", "an"}


def norm(desc: str | None) -> str:
    d = (desc or "").strip()
    prev = None
    while prev != d:
        prev = d
        d = _LEAD.sub("", d, count=1).strip()
    return d


def naive(desc: str | None) -> bool:
    return bool(NAIVE.search(desc or ""))


def _headed(desc: str | None) -> bool:
    """HEAD then TRIM (the D0's V2): an order-type head, not a procedural subject."""
    d = desc or ""
    if _REMOVED.match(d):
        return False
    n = norm(d)
    if not HEAD.match(n):
        return False
    if NOA_HEAD.match(n):             # a notice of appeal is never trimmed
        return True
    return not (PROCEDURAL.search(n) and not PROTECT.search(n))


def order_like_text(desc: str | None) -> bool:
    """The test on one description, before short-form resolution (the D0's V3)."""
    d = desc or ""
    if _REMOVED.match(d):
        return False
    return _headed(d) or bool(DISPO.search(norm(d)))


def entry_token(url: str | None) -> str | None:
    """The docket entry number (district) or document id (appellate) in a CourtListener
    document_url -- the only entry-number signal the table has."""
    m = re.search(r"/docket/\d+/([^/]+)/", url or "")
    return m.group(1) if m else None


def is_short(desc: str | None) -> bool:
    return len(norm(desc)) <= SHORT


def twins(row: dict, docket_rows: list[dict]) -> list[dict]:
    """A short-form row's long-form twins on its own docket: the same entry token, or
    (no token) the same entry_at, order-headed, and carrying every content word of the
    short form."""
    if not is_short(row["description"]):
        return []
    tok = entry_token(row.get("document_url"))
    words = [w for w in re.findall(r"[a-z]+", (row["description"] or "").lower())
             if w not in _STOP and len(w) > 2]
    out = []
    for o in docket_rows:
        if o is row or is_short(o["description"]):
            continue
        if tok is not None:
            if entry_token(o.get("document_url")) == tok:
                out.append(o)
        elif (o["entry_at"] == row["entry_at"] and HEAD.match(norm(o["description"]))
              and words and all(w in (o["description"] or "").lower() for w in words)):
            out.append(o)
    return out


def classify(row: dict, docket_rows: list[dict]) -> str | None:
    """None when the row does not flag; "flag" when it does; "unreadable" when it flags
    as a short form with no readable twin (the D0's V4)."""
    if not order_like_text(row["description"]):
        return None
    sib = twins(row, docket_rows)
    if sib:
        return "flag" if any(order_like_text(s["description"]) for s in sib) else None
    return "unreadable" if is_short(row["description"]) else "flag"


# --------------------------------------------------------------------------- #
# The readings, off docs/gates.yaml
# --------------------------------------------------------------------------- #
def load_gates(path: Path | None = None) -> list[dict]:
    return yaml.safe_load((path or GATES_PATH).read_text(encoding="utf-8"))


def _iso(v) -> str | None:
    """A YAML date arrives as a date under safe_load and as a string when quoted."""
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return v
    return None


def listed_gates(gates: list[dict]) -> list[dict]:
    """The authored, unfalsified gates that list a docket: the ones a flag can reach."""
    return [g for g in gates
            if g.get("kind") == "authored" and g.get("status") != "falsified"
            and g.get("record_instruments")]


def reading_problems(gates: list[dict]) -> list[str]:
    """What is wrong with the readings. assert-gates refuses the same shapes (exit 3);
    this is the Python side's own guard, so the audit never reads a watermark it
    cannot trust."""
    out = []
    for g in gates:
        if not isinstance(g, dict):
            continue
        rr = g.get("record_read")
        listed = [str(c) for c in (g.get("record_instruments") or [])]
        if rr is None:
            if listed:
                out.append(f"{g.get('id')}: lists {', '.join(listed)} and carries no record_read")
            continue
        if not isinstance(rr, list):
            out.append(f"{g.get('id')}: record_read must be a list")
            continue
        seen = collections.Counter()
        for i, r in enumerate(rr):
            at = f"{g.get('id')}: record_read[{i}]"
            if not isinstance(r, dict):
                out.append(f"{at}: not a mapping")
                continue
            extra = set(r) - READING_KEYS
            missing = READING_KEYS - {"verdicts"} - set(r)
            if extra:
                out.append(f"{at}: unknown keys {sorted(extra)}")
            if missing:
                out.append(f"{at}: missing {sorted(missing)}")
            d = str(r.get("docket", ""))
            seen[d] += 1
            if d not in listed:
                out.append(f"{at}: docket {d} is not in record_instruments")
            if _iso(r.get("read_on")) is None or _iso(r.get("through_entry_at")) is None:
                out.append(f"{at}: read_on and through_entry_at must be YYYY-MM-DD")
            if not isinstance(r.get("through_entry_id"), int) or r.get("through_entry_id") < 0:
                out.append(f"{at}: through_entry_id must be a non-negative integer")
            v = r.get("verdicts") or {}
            if not isinstance(v, dict):
                out.append(f"{at}: verdicts must be a mapping of entry id to verdict")
            else:
                for k, val in v.items():
                    if not re.fullmatch(r"\d+", str(k)) or val not in VERDICTS:
                        out.append(f"{at}: verdict {k}: {val!r} (entry ids map to "
                                   f"{' | '.join(VERDICTS)})")
        for d in listed:
            if seen[d] != 1:
                out.append(f"{g.get('id')}: listed docket {d} has {seen[d]} readings (expect 1)")
    return out


def readings(gates: list[dict]) -> list[dict]:
    """One row per (gate, listed docket): the watermark a flag is measured from."""
    out = []
    for g in listed_gates(gates):
        by_docket = {str(r["docket"]): r for r in g.get("record_read") or []}
        for c in g["record_instruments"]:
            r = by_docket[str(c)]
            out.append({"gate": g["id"], "docket": str(c), "read_on": _iso(r["read_on"]),
                        "through_entry_id": int(r["through_entry_id"]),
                        "through_entry_at": _iso(r["through_entry_at"]),
                        "verdicts": {int(k): v for k, v in (r.get("verdicts") or {}).items()}})
    return out


def reason_readings(seeds: list[dict]) -> list[dict]:
    """One row per docket cleared by a no-claim-order reason: watched from its read-through
    date (Corey, 2026-09-29)."""
    out = []
    for s in seeds or []:
        gc = s.get("gate_coverage") if isinstance(s, dict) else None
        if isinstance(gc, dict) and gc.get("unlisted") == "no-claim-order" and s.get("case_id"):
            d = _iso(gc.get("read_through"))
            if d:
                v = gc.get("verdicts") or {}
                out.append({"gate": "gate_coverage: no-claim-order", "docket": str(s["case_id"]),
                            "read_on": d, "through_entry_id": None, "through_entry_at": d,
                            "verdicts": {int(k): x for k, x in v.items()} if isinstance(v, dict) else {},
                            "reason": True, "ruled": gc.get("ruled")})
    return out


def load_seeds(path: Path | None = None) -> list[dict]:
    doc = yaml.safe_load((path or ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    return (doc.get("litigation") or {}).get("seed_cases") or []


def tally(gates: list[dict], seeds: list[dict] | None = None) -> collections.Counter:
    """The measurement so far: verdicts recorded on every reading of every gate, and on
    every no-claim-order reason."""
    c = collections.Counter()
    for g in gates:
        for r in (g.get("record_read") or []) if isinstance(g, dict) else []:
            for v in (r.get("verdicts") or {}).values():
                c[v] += 1
    for r in reason_readings(seeds or []):
        for v in r["verdicts"].values():
            c[v] += 1
    return c


# --------------------------------------------------------------------------- #
# Flags against the held entries
# --------------------------------------------------------------------------- #
def fetch_rows(conn, dockets: list[str]) -> dict[str, list[dict]]:
    """Every held entry of the listed dockets. All of a docket's rows, not only those
    above its watermark: a short form's readable twin may sit below it."""
    if not dockets:
        return {}
    marks = ",".join("?" for _ in dockets)
    rows = conn.execute(
        "SELECT id, case_id, entry_at, description, document_url FROM case_entries "
        f"WHERE case_id IN ({marks}) ORDER BY id", tuple(dockets)).fetchall()
    out: dict[str, list[dict]] = {d: [] for d in dockets}
    for r in rows:
        out[str(r["case_id"])].append({k: r[k] for k in
                                       ("id", "case_id", "entry_at", "description", "document_url")})
    return out


def flags(read: list[dict], rows_by_docket: dict[str, list[dict]]) -> list[dict]:
    """Per reading: the held MAX(id) and MAX(entry_at), and the flagged and naive rows
    above its watermark. Pure, over rows handed in, so the suite never reads live data."""
    out = []
    for r in read:
        rows = rows_by_docket.get(r["docket"], [])
        if r.get("reason"):   # a no-claim-order docket: entries FILED after the date
            above = [x for x in rows if (x["entry_at"] or "")[:10] > r["through_entry_at"]]
        else:
            above = [x for x in rows if x["id"] > r["through_entry_id"]]
        flagged = []
        for x in above:
            kind = classify(x, rows)
            if kind:
                flagged.append({**x, "kind": kind})
        max_id = max((x["id"] for x in rows), default=None)
        out.append({**r, "held": len(rows), "max_id": max_id,
                    "max_entry_at": max(((x["entry_at"] or "")[:10] for x in rows), default=None),
                    "above": len(above), "flagged": flagged,
                    "naive": sum(1 for x in above if naive(x["description"])),
                    # A watermark above everything held suppresses every flag on the
                    # docket, and a hand-edited number can be a typo or a paste from
                    # another docket: say so rather than stay quiet.
                    "ahead": (not r.get("reason")) and r["through_entry_id"] > (max_id or 0)})
    return out


def report_lines(result: list[dict], counts: collections.Counter) -> list[str]:
    """Section 9's body, as coverage_audit prints it."""
    nflag = sum(len(r["flagged"]) for r in result)
    nnaive = sum(r["naive"] for r in result)
    nlisted = sum(1 for r in result if not r.get("reason"))
    lines = [f"  [9] RECHECK FLAGS -- order-like entries on watched dockets: {nflag} on "
             f"{sum(1 for r in result if r['flagged'])} of {len(result)} ({nlisted} listed, "
             f"above a gate's reading; {len(result) - nlisted} by no-claim-order read-through "
             f"date)  (a report, not an alarm; the naive count beside it: {nnaive})"]
    got = sum(counts.values())
    lines.append(f"      verdicts so far: {got} ({counts['operative']} operative, "
                 f"{counts['noise']} noise, {counts['missed']} missed, {counts['duplicate']} "
                 f"duplicate, {counts['unread']} unread). The ruled bar, not yet in force: 0 "
                 f"missed and at most 1/3 noise, over {VERDICTS_NEEDED}+ verdicts and through "
                 f"{PERIOD_END}.")
    # UNREAD IS OPEN (ruled 2026-09-29), whatever the watermark: every one prints.
    for r in result:
        for k, v in sorted((r.get("verdicts") or {}).items()):
            if v == "unread":
                lines.append(f"      UNREAD, STILL OPEN: {k} on {r['docket']} ({r['gate']}) -- "
                             f"give a verdict once its text is read")
    for r in result:
        if r.get("reason"):
            lines.append(f"      {r['gate']} / {r['docket']}: read through {r['through_entry_at']} "
                         f"({r.get('ruled')}); watched by filing date; {r['above']} filed after, "
                         f"{len(r['flagged'])} flagged, {r['naive']} naive")
        else:
            lines.append(f"      {r['gate']} / {r['docket']}: read {r['read_on']} through id "
                         f"{r['through_entry_id']} ({r['through_entry_at']}); held max id "
                         f"{r['max_id']}; {r['above']} above, {len(r['flagged'])} flagged, "
                         f"{r['naive']} naive")
        if r.get("reason") and r["flagged"]:
            lines.append("        THE NO-CLAIM-ORDER REASON NEEDS RE-RULING: an order-like entry "
                         "was filed after its read-through date")
        if r.get("ahead"):
            lines.append(f"        WATERMARK AHEAD OF THE RECORD: through id {r['through_entry_id']} > "
                         f"held max {r['max_id']}; no entry on this docket can flag until it is fixed")
        for x in r["flagged"]:
            tag = "UNREADABLE " if x["kind"] == "unreadable" else ""
            given = r.get("verdicts", {}).get(x["id"])
            lines.append(f"        FLAG {tag}{x['id']:<7} {(x['entry_at'] or '')[:10]}  "
                         f"{' '.join((x['description'] or '').split())[:120]}"
                         + (f"  [verdict: {given}]" if given else ""))
    return lines


def posted_ids(text: str) -> set[int]:
    """Entry ids already posted, from the markers every flag comment carries."""
    out = set()
    for m in MARKER.finditer(text or ""):
        out |= {int(t) for t in re.findall(r"\d+", m.group(1))}
    return out


def comment_body(result: list[dict], already: set[int], run_url: str = "") -> str | None:
    """The standing issue's comment for flags not yet posted, or None when there are
    none. Worded as a flag, not a failure (Corey, 2026-09-29)."""
    new = [(r, x) for r in result for x in r["flagged"] if x["id"] not in already]
    if not new:
        return None
    ids = sorted({x["id"] for _, x in new})
    where = []
    if any(not r.get("reason") for r, _ in new):
        where.append("on a docket a gate lists, above its last reading")
    if any(r.get("reason") for r, _ in new):
        where.append("on a docket cleared by a no-claim-order reason, filed after its "
                     "read-through date")
    out = ["cc @CSU-J3", "",
           f"**Recheck flag** -- {len(ids)} new order-like "
           f"{'entry' if len(ids) == 1 else 'entries'} {' and '.join(where)}. A flag asks for "
           "a read; it is not a failure, and it never turns a run red.", ""]
    if run_url:
        out += [f"Run: {run_url}", ""]
    reasons = sorted({r["docket"] for r, _ in new if r.get("reason")})
    if reasons:
        out += [f"**The no-claim-order reason on {', '.join(reasons)} needs re-ruling:** an "
                "order-like entry was filed after its read-through date. Read it, then list the "
                "docket on the gate it bears on or record a new read-through date.", ""]
    out += ["| entry | filed | gate | docket | text |", "|---|---|---|---|---|"]
    pending = 0
    for r, x in new:
        text = " ".join((x["description"] or "").split()).replace("|", "/")[:220]
        tag = " (short form: content only in the PDF)" if x["kind"] == "unreadable" else ""
        given = (r.get("verdicts") or {}).get(x["id"])
        if given:
            tag += f" **[verdict recorded: {given}]**"
        else:
            pending += 1
        out.append(f"| {x['id']} | {(x['entry_at'] or '')[:10]} | `{r['gate']}` | "
                   f"[{r['docket']}]({COURTLISTENER_DOCKET.format(r['docket'])}) | {text}{tag} |")
    if pending:
        out += ["", "Reply with a verdict per entry not marked recorded -- **operative**, "
                "**noise**, **duplicate** (the same order or notice held as a second row) or "
                "**unread** (open until its text is read) -- and any operative entry the flags "
                "missed. The verdicts are the measurement: they go on the gate's `record_read` "
                "when its reading moves, or on the no-claim-order reason's `verdicts`, beside "
                "those already given (`python -m tools.recheck_flags --fragment`)."]
    else:
        out += ["", "Every entry above already carries a recorded verdict; nothing is asked."]
    out += ["", f"<!-- recheck-flags: {','.join(map(str, ids))} -->"]
    return "\n".join(out) + "\n"


def fragment(result: list[dict]) -> str:
    """A reading's YAML, per listed docket, for a person to fill in and commit: the held
    MAX(id) and MAX(entry_at) now, and the flagged ids above the current watermark, each
    awaiting a verdict. The audit never writes it."""
    out = [f"# recheck_flags --fragment: the held record now. Read each docket against its "
           f"gate's claim, give each flagged id a verdict, record any unflagged operative "
           f"entry as missed, then replace the gate's record_read item. The verdicts it "
           f"already carries are kept: they accumulate."]
    for r in result:
        if r.get("reason"):
            out.append(f"# {r['docket']}: cleared by a no-claim-order reason read through "
                       f"{r['through_entry_at']}. "
                       + (f"{len(r['flagged'])} flag(s) filed after it: re-rule the reason "
                          f"(list the docket, or a new read_through on its seed), and record "
                          f"each flag's verdict on the reason:"
                          if r["flagged"] else "Nothing filed after it flags."))
            if r["flagged"]:
                prior = r.get("verdicts") or {}
                out.append("#   gate_coverage.verdicts:")
                out += [f"#     {k}: {v}" for k, v in sorted(prior.items())]
                out += [f"#     {x['id']}: {SLOT}    # {(x['entry_at'] or '')[:10]} "
                        f"{' '.join((x['description'] or '').split())[:70]}"
                        for x in r["flagged"] if x["id"] not in prior]
            continue
        out += [f"# {r['gate']}", f"  - docket: \"{r['docket']}\"",
                "    read_on: YYYY-MM-DD",
                f"    through_entry_id: {r['max_id'] if r['max_id'] is not None else 0}",
                f"    through_entry_at: {r['max_entry_at'] or 'YYYY-MM-DD'}"]
        prior = r.get("verdicts") or {}
        new = [x for x in r["flagged"] if x["id"] not in prior]
        if prior or new:
            out.append("    verdicts:")
            out += [f"      {k}: {v}" + ("    # STILL OPEN: replace once its text is read"
                                             if v == "unread" else "")
                    for k, v in sorted(prior.items())]
            out += [f"      {x['id']}: {SLOT}    # {(x['entry_at'] or '')[:10]} "
                    f"{' '.join((x['description'] or '').split())[:80]}" for x in new]
        else:
            out.append("    verdicts: {}")
    return "\n".join(out) + "\n"


def compute(conn, gates: list[dict], seeds: list[dict] | None = None) -> list[dict]:
    problems = reading_problems(gates)
    if problems:
        raise ValueError("docs/gates.yaml record_read is malformed: " + "; ".join(problems))
    read = readings(gates) + reason_readings(load_seeds() if seeds is None else seeds)
    return flags(read, fetch_rows(conn, sorted({r["docket"] for r in read})))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--fragment", action="store_true")
    ap.add_argument("--comment-body", metavar="FILE")
    ap.add_argument("--posted", metavar="FILE", help="text holding the flag markers already posted")
    ap.add_argument("--run-url", default="")
    args = ap.parse_args(argv)

    import config
    import db
    config.load_env()
    gates = load_gates()
    conn = db.connect()
    try:
        result = compute(conn, gates)
    finally:
        conn.close()

    if args.fragment:
        sys.stdout.write(fragment(result))
    elif args.comment_body:
        already = set()
        if args.posted and Path(args.posted).exists():
            already = posted_ids(Path(args.posted).read_text(encoding="utf-8"))
        body = comment_body(result, already, args.run_url)
        target = Path(args.comment_body)
        if body is None:
            target.write_bytes(b"")
            print("recheck_flags: no new flags")
        else:
            target.write_bytes(body.encode("utf-8"))
            print(f"recheck_flags: {len(posted_ids(body))} new flag(s) written to {target}")
    else:
        print("\n".join(report_lines(result, tally(gates, load_seeds()))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

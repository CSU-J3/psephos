"""Nine read-only coverage questions about `cases`, the tracker artifact,
`state_bills`, the collect lane's `channel_runs` and the gate register's readings, in
one pass. Writes nothing.

This is what survived the handoff 17 supersession-generator unit. That unit proposed a
two-input pair detector behind a three-predicate cascade; it was measured (handoff 40-42)
and declined as REDUNDANT, not ineffective -- see docs/status.md. The measurement that
killed the detector is the same one that found the gaps in section 2, so the regex below
is not new code on an untested idea: it is the one component of that work with known
behaviour, kept because it was measured on this exact corpus.

    python -m tools.coverage_audit

Exit code is the ALARM in sections 1, 4, 5, 6, 7 and 8: 1 if any row is unreconciled, OR
any row's `latest_entry_at` disagrees with its derivation, OR any tracker court fails to
classify, OR any row was never polled and is linked to nothing, OR any state bill carries
a non-null status outside LegiScan's six, OR no collect run has written a `channel_runs`
row for longer than the lane ever went quiet in its history. All six expect 0.
Sections 2 and 3 are REPORTS and are expected to be non-empty -- 6 and 1 as of
2026-09-07. Do not read a non-zero count there as a failure. Section 9 is a REPORT too,
by ruling (Corey, 2026-09-29): recheck flags, order-like entries on a gate-listed docket
above its last reading (tools/recheck_flags.py), with the naive count beside them. It
stays out of the exit code until its measurement clears the ruled bar; audit.yml
delivers its flags as comments on a standing issue that never turns a run red.

(Section 4 was added 2026-08-14 and the exit code widened with it. It used to read
"the ALARM in section 1 only", which is why this line is restated rather than left to
be inferred from the code. Sections 5 and 6 were added 2026-09-07 with unit C and it
widened again -- the same restatement, for the same reason. Section 7 was added
2026-09-26 and it widened a third time; section 8 on 2026-09-28, a fourth.)

DELIVERY IS THE POINT OF UNIT C, NOT DETECTION. Every alarm here was correct and
available before it was read: section 1 read 6 for seventeen days, and tracker_uw's
unmapped-court WARN -- section 5's subject -- fired four times a day into a stderr
nothing reads. This script exits non-zero so that .github/workflows/audit.yml can
turn that into a standing GitHub issue a person has to close. Run on demand too;
read the exit status directly, never through a pipe, which reports the pager's.

--- section 1, the reconciliation alarm --------------------------------------
A row in `cases` matching no seed AND carrying no `superseded_by` is a row nothing
polls and nothing links. That is exactly the state KY, VA and NM sat in: the UW
tracker rewrote each state's row to point at its circuit appeal, the district row
stopped being seeded, and nothing noticed for weeks. This alarm would have fired on
07-28 and 07-31, days after each rewrite.

It replaces the cross-reference pair detector on the merits. That rule found 5 pairs,
all 5 real -- and all 5 already asserted, with zero rewrite signals across the nine
unlinked terminated rows. One join against a cascade of three predicates, a regex and
a corpus decision. Redundant against a cheaper instrument.

THE ORDERING TRAP (handoff 26 section 3, shipped as a bug once). The seed set is the
UNION of both sources: config/sources.yaml -> litigation.seed_cases plus
data/doj_cases.json, which is the list `litigation.main()` actually iterates. The
tool's header line prints the live seed-key count; read it there. (This paragraph
carried the figures twice -- 2 + 34, then 8 + 32 = 40 -- and both went stale as the
config side grew, the second when the EO 14399 seeds landed on 2026-09-27.)

Against the ARTIFACT ALONE the numbers change and both are easy to misquote:
8 rows read unseeded rather than 6, and the ALARM reads 2 rather than 0 -- the two
extras being the config seeds, which are polled every run. (Counts as of unit C; the
config seeds have grown since, so re-read them rather than quoting these.) 8 is the unseeded count and
2 is the alarm count; they are different questions and neither is the other. Reuse
`status_audit.seeded_keys` rather than rebuilding the join, so there is one definition
to be wrong in.

Join key is `(docket_number, court)`, exact by construction: `upsert_case` writes
`"court": seed.get("court")` straight off the seed.

--- section 2, unresolvable docket references --------------------------------
A docket number named in `case_entries.description` that matches no row psephos holds.
Every one on this corpus is a real reference to a real case, and four are coverage
defects worth acting on: `26-5243` is a D.C. Circuit appeal the project does not hold,
and `2:25-cv-09149` / `6:25-cv-01666` / `2:26-cv-00066` are the CA, OR and AZ DISTRICT
ORIGINALS sitting behind Ninth Circuit rows psephos does hold. Holding an appeal
without its underlying case is a gap nothing else in the project reports.

Corpus is `case_entries`, NEVER data/cases.json. The snapshot's `timeline` is built
from `items`, not `case_entries` -- half the rows (1,958 against 4,043) and the
survivors truncated near 200 characters -- so the text this rule reads is not in it.

DATES ARE STRIPPED FIRST, and they have to be. `held on 10-28-2025` yields `28-2025`
under the docket pattern, and `Date of Issuance: 10-30-2025` yields `30-2025`; both
appeared as "coverage gaps" before this filter. Residual risk is stated rather than
solved: a real circuit docket of the form `26-2025` sitting inside a date-shaped
string would be stripped with it. Full MM-DD-YYYY context is strong enough evidence to
take that trade, but it is a trade.

No cascade here. The pair-forming logic that used to sit on top of this regex is the
part that was declined; the parsing was never the weak half.

--- section 3, the cert watch list -------------------------------------------
Terminated circuit rows with no successor. A terminated DISTRICT row continues as an
appeal; a terminated CIRCUIT row's only continuation is a cert petition, and nothing
in psephos resolves one. Michigan `72347022` (6th Cir. 26-1225, AFFIRMED 06-24, en
banc petition 07-10) is the standing case -- en banc stays on the same docket, so it
is not a supersession, and no cert petition exists yet, so its NULL is correct today.

The shape IS reachable if it ever needs building: CourtListener carries 2,548 SCOTUS
dockets filed since 2026-01-01 with clean `docket_number` and `date_filed`. INSTRUMENT
NOTE -- query them with `date_filed__gte`. An unfiltered `order_by=-date_filed` returns
historical imports with NULL dates and duplicated ids, which reads as dead coverage.

--- section 8, the dead-lane alarm (unit 99, ruling 2b) ------------------------
A collect run that never happens cannot report itself: collect.yml's Verdict step and
heartbeat are steps OF the run. Read 2026-09-28, nothing outside collect.yml alarmed
when collect stopped: the homepage's run-status element turns "missing" after 6h10m but
tells no one, dom-checks renders it daily and asserts nothing on it, and no section here
read freshness. Worse, a stopped collect freezes data/generated_at.json, which disarms
dom-checks' gate-expiry checks, since they compare against it.

So this section reads the newest `channel_runs` row a collect.yml run wrote -- every
run whose legislation gets past its database connection writes one -- and fires when it
is older than COLLECT_SILENCE_MAX_HOURS, or when there is no such row or no table. A
LOCAL run's rows (run_id 'local', e.g. a seed proved against Turso from a workstation)
are not the collect lane and are not counted: the likeliest time for one is while
someone debugs a broken lane, which is exactly when this must not go quiet. A row
stamped more than an hour AHEAD of now fires too: only a broken writer clock makes one,
and it would otherwise hold the alarm off until 24h past its stamp.

The bound is MEASURED, not chosen (ruling 2b: accepted only if it stays silent across
the history the receipts were checked against). Over the 368 retained collect.yml runs,
2026-06-29 to 2026-09-28, 361 would have written a row. Of the seven that would not,
four died at the schema step (the 07-31 read block and the three 08-06/07 Turso 502s),
two died inside legislation's first bill on a dead Hrana stream (the handoff-15 rollback
crash db.recover now absorbs, so 361 is a floor), and one, the first dispatch, was
cancelled. The longest gap between two row-writing runs is 23h06m58s, 2026-08-06T13:30Z
to 2026-08-07T12:37Z, the 502 incident; the longest with no incident is 16h08m26s
(2026-09-14/15, slots GitHub never fired). 24h stays silent at every gap, at the 21 real
scheduled audit read times (the oldest row any would have seen, reconstructed from the
collect logs, was 6h13m) and at daily reads replayed over the whole history. It fires at
the first audit read after the lane has been quiet a full day: about 24h to 50h after
the last row, with one dropped audit slot adding a day.

NOT THE 2026-09-09 REFUSAL AGAIN (docs/status.md, *THE CHANNEL AGE ALARM IS REFUSED*).
That refused a per-channel age alarm on `items.fetched_at`, which measures how often
upstream produces events, and it refused for margin: its least-silent bounds sat 1.03x and
1.09x over the second-largest gap. This reads the per-run receipt that entry named and
left unbuilt, and on the same test reads 1.43x (23h06m58s over 16h08m26s). The
`fetched_at` refusal stands.
"""
from __future__ import annotations

import re
import textwrap
from datetime import date, datetime, timezone
from pathlib import Path

import config
import db
from collectors.litigation import load_tracker_seeds
from collectors.tracker_uw import COURT_IDS
from tools import recheck_flags
from tools.status_audit import seeded_keys

# Year-dash forms only. District: 1:25-cv-03934. Circuit: 26-2684. The {3,5} tail is
# what excludes docket-entry brackets -- [6], [32] carry no dash and never match.
DISTRICT_DOCKET = re.compile(r"\b\d:\d{2}-[a-z]{2}-\d{4,5}\b", re.I)
CIRCUIT_DOCKET = re.compile(r"\b\d{2}-\d{3,5}\b")
DATE_LIKE = re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b")

# LegiScan's status codes that /state-bills puts on its ramp: Introduced, Engrossed,
# Enrolled, Passed, Vetoed, Failed. Written out here rather than imported, because the
# ramp's owner is web/lib/statebill.ts (STAGE_ORDER), which Python cannot import; section
# 7 asserts every non-null status the collector stored is one of these.
STATE_BILL_STATUSES = ("1", "2", "3", "4", "5", "6")


def unreconciled(rows, seeded) -> list:
    """Section 1. Rows matching no seed and carrying no `superseded_by`."""
    return [r for r in rows
            if (r["docket_number"], r["court"]) not in seeded
            and r["superseded_by"] is None]


# --- the acknowledged-blocked register, section 1's exit-code filter ------------------
#
# AN ACKNOWLEDGEMENT, NOT A SUPPRESSION. The vocabulary is docs/gates.yaml's, whose
# header states the same mechanism for a different check: "`status: stale` IS AN
# ACKNOWLEDGEMENT, NOT A SUPPRESSION ... The grey is the reader's signal and it is never
# silenced." Here an acknowledged row leaves the EXIT CODE and nothing else -- it still
# prints in section 1, marked, carrying its condition. The report never gets quieter
# than the record.

# Repo-relative, matching tools.status_audit.IN_TRACKER: every entry point chdirs to
# the repo root, and the tests do so explicitly.
ACKS_PATH = "docs/audit-acks.yaml"

ACK_REQUIRED = ("case_id", "docket_number", "court", "blocked_because",
                "unblocked_when", "acknowledged_on", "review_by")
ACK_OPTIONAL = ("successor", "note")

# The CLOSED VOCABULARY for `unblocked_when`, as predicates over a `cases` row. A
# condition nothing can evaluate is a comment, so prose is not accepted here. Every
# predicate reads a column main() already SELECTs, so the register costs no extra query.
ACK_CONDITIONS = {
    "source_terminated": lambda r: (r["status"] or "").strip().lower() == "terminated",
}


def load_acks(path=None) -> list[dict]:
    """Read and VALIDATE docs/audit-acks.yaml. Raises ValueError on any bad shape.

    THE assert-gates.mjs:93 HAZARD, DESIGNED OUT RATHER THAN INHERITED. That script's
    header records that a MISSPELLED `recheck_after` would let an expired claim pass,
    because the check reads a named field and a typo makes it absent rather than wrong.
    The same typo here would be worse: a misspelt `unblocked_when`, or a value outside
    the vocabulary, would make an entry that can never lapse -- a permanent silencer
    created by a slip. So nothing falls through inert: an unknown field, a missing
    required field, and an unrecognised `unblocked_when` are each a hard refusal, and
    the audit fails loudly rather than running with a register it half-understands.
    """
    import datetime
    import yaml

    path = Path(path) if path else Path(ACKS_PATH)
    if not path.exists():
        return []
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(doc, list):
        raise ValueError(f"{path}: expected a list of entries, got {type(doc).__name__}")
    out = []
    for i, e in enumerate(doc):
        at = f"{path}: entry {i}"
        if not isinstance(e, dict):
            raise ValueError(f"{at}: expected a mapping")
        unknown = set(e) - set(ACK_REQUIRED) - set(ACK_OPTIONAL)
        if unknown:
            raise ValueError(f"{at}: unknown field(s) {sorted(unknown)}")
        missing = [f for f in ACK_REQUIRED if f not in e]
        if missing:
            raise ValueError(f"{at}: missing required field(s) {missing}")
        if e["unblocked_when"] not in ACK_CONDITIONS:
            raise ValueError(
                f"{at}: unblocked_when {e['unblocked_when']!r} is not in the closed "
                f"vocabulary {sorted(ACK_CONDITIONS)} -- an unrecognised value is "
                f"refused rather than treated as never-firing")
        for f in ("acknowledged_on", "review_by"):
            if not isinstance(e[f], datetime.date):
                raise ValueError(f"{at}: {f} must be a YAML date, got {e[f]!r}")
        out.append(dict(e, case_id=str(e["case_id"])))
    return out


def ack_lapse(row, ack, today) -> str | None:
    """Why this acknowledgement does not apply to this row, or None if it holds.

    THREE WAYS TO LAPSE, checked in this order because they mean different things.

    The CORROBORATOR check runs first, and it is the one P0 added. `court` and
    `docket_number` are written straight off the seed (collectors/litigation.py:334), so
    they FREEZE when a row stops being seeded and survive the un-seed that fires section
    1. What they do not survive is a RE-SEED under a different spelling, which rewrites
    both -- and an entry keyed on the old pair would then stop applying SILENTLY, since
    a re-seeded row does not fire anyway. Drop it again later and the alarm returns with
    no explanation. Matching on `case_id` and CHECKING the pair turns that silent lapse
    into a loud one.

    Then the CONDITION, which is the designed happy path: the block is over and the
    alarm should be demanding the work again. Then the EXPIRY, the backstop for a
    condition that never fires.
    """
    if (str(row["docket_number"]) != str(ack["docket_number"])
            or str(row["court"]) != str(ack["court"])):
        return (f"the row moved -- acknowledgement carries "
                f"{ack['docket_number']} / {ack['court']}")
    if ACK_CONDITIONS[ack["unblocked_when"]](row):
        return f"condition fired -- {ack['unblocked_when']}"
    if ack["review_by"] < today:
        return f"expired -- review_by {ack['review_by']}"
    return None


def partition_alarm(alarm, acks, today):
    """Split section 1's firing rows three ways. ONLY the first counts.

    Returns (unacknowledged, blocked, lapsed); `blocked` and `lapsed` carry the entry,
    and `lapsed` carries the reason, because a row that returns to the count has to say
    why or the register becomes a thing that stops working quietly.
    """
    by_id = {a["case_id"]: a for a in acks}
    unack, blocked, lapsed = [], [], []
    for r in alarm:
        ack = by_id.get(str(r["case_id"]))
        if ack is None:
            unack.append(r)
            continue
        why = ack_lapse(r, ack, today)
        (lapsed.append((r, ack, why)) if why else blocked.append((r, ack)))
    return unack, blocked, lapsed


def dangling_acks(alarm, acks) -> list[dict]:
    """Entries whose row is not firing at all -- linked, re-seeded, or gone.

    Reported, never counted. An entry that outlives its row is the same rot the expiry
    exists for, and it costs one set difference to say so.
    """
    firing = {str(r["case_id"]) for r in alarm}
    return [a for a in acks if a["case_id"] not in firing]


def unresolvable_refs(conn, held: set[str]) -> dict[str, list[tuple[str, str]]]:
    """Section 2. token -> [(naming case_id, the entry text)], dates stripped first."""
    found: dict[str, list[tuple[str, str]]] = {}
    for e in conn.execute("SELECT case_id, description FROM case_entries").fetchall():
        text = DATE_LIKE.sub(" ", e["description"] or "")
        for tok in set(DISTRICT_DOCKET.findall(text)) | set(CIRCUIT_DOCKET.findall(text)):
            if tok not in held:
                found.setdefault(tok, []).append(
                    (e["case_id"], " ".join((e["description"] or "").split())))
    return found


def classify_ref(tok: str, naming_courts: list[str], naming_dockets: list[str]) -> str:
    """Which KIND of gap a section-2 reference is. Three, not one.

    THE LIST USED TO BE UNDIFFERENTIATED AND WAS READ AS ONE CANDIDATE, which is
    what this exists to prevent. The distinction was already written down -- in this
    module's docstring -- and the docstring is not what a reader of the output sees.
    Information in the wrong place is not available.

      predecessor  a DISTRICT-form token named by a CIRCUIT row: psephos holds the
                   appeal and not the case under it. Seed and supersede FORWARD.
      successor    a CIRCUIT-form token named by a district row: psephos holds the
                   original and not what continued it. Seed and supersede BACKWARD.
      self-ref     the token is the naming row's OWN docket in another notation.
                   Arizona's local `CV-26-00066-PHX-SMB` renders the held
                   `2:26-cv-00066` as the token `26-00066`. Noise, not a gap.

    Self-reference is matched on DIGITS ONLY, after dropping the court-division
    prefix, so `26-00066` matches `2:26-cv-00066`. Residual risk is stated rather
    than solved, the same trade DATE_LIKE takes above: a genuine circuit docket
    whose digits happen to be a suffix of its naming row's district number would be
    dismissed as noise. Both regexes and both fields were already in hand.
    """
    digits = lambda s: re.sub(r"\D", "", s or "")
    if any(digits(d).endswith(digits(tok)) for d in naming_dockets if d):
        return "self-ref"
    is_district = bool(DISTRICT_DOCKET.fullmatch(tok))
    named_by_circuit = any((c or "").strip().endswith("Circuit") for c in naming_courts)
    if is_district and named_by_circuit:
        return "predecessor"
    if not is_district and not named_by_circuit:
        return "successor"
    return "reference"


def cert_watch(rows) -> list:
    """Section 3. Terminated circuit rows with no successor."""
    return [r for r in rows
            if (r["court"] or "").strip().endswith("Circuit")
            and (r["status"] or "").lower() == "terminated"
            and r["superseded_by"] is None]


def derived_drift(conn) -> list:
    """Section 4: rows where `cases.latest_entry_at` disagrees with its own derivation,
    MAX(record_entries.entry_at) -- the latest ENTRY, at its date now, since the R1 switch
    (a re-dated entry's stale row no longer counts). An ALARM, expected 0.

    A derived column acquired 12 disagreements silently and nothing noticed for three
    weeks. `write_entries` assigned the max date_filed of the POLLED BATCH, correct
    while every poll was a full walk and wrong from c8b8b6f (2026-07-22) onward, when
    the batch became a date_modified window that can hold only a late-backfilled old
    filing. The column walked BACKWARDS -- West Virginia read 2026-05-15 while holding
    an entry from 2026-08-06 -- and the first thing to notice was a dormancy display
    built on it three weeks later, which reported a false positive on its first render.

    The check costs one statement and existed all along, which is the whole argument
    for it being here: the same alarm philosophy as section 1, applied to a column
    whose correctness nothing else asserts. The write path is fixed and the historical
    drift is repaired (scripts/repair_latest_entry.py), so a non-zero here is a NEW
    defect at an insert site, not the old one recurring.

    LEFT JOIN so a case with no entries appears rather than vanishing: NULL derived
    against a non-NULL stored is its own defect and should fire, not hide."""
    out = []
    for r in conn.execute(
        "SELECT c.case_id, c.court, c.docket_number, c.latest_entry_at AS stored, "
        "       MAX(e.entry_at) AS derived "
        "FROM cases c LEFT JOIN record_entries e ON e.case_id = c.case_id "
        "GROUP BY c.case_id ORDER BY c.case_id"
    ).fetchall():
        if r["stored"] != r["derived"]:
            out.append(r)
    return out


def unclassified_courts(seeds: list[dict]) -> list[dict]:
    """Section 5: tracker-artifact rows whose court does not classify. ALARM, expect 0.

    THE SUBJECT IS THE ARTIFACT, NOT `cases`, and that scoping is a correction rather
    than a preference. `COURT_IDS` exists for exactly one job: turning a court NAME
    scraped by tracker_uw into a CourtListener id. Config seeds in
    config/sources.yaml carry a hand-authored `court_id` and never consult it --
    `collect_case` reads `seed.get("court_id")` off whichever seed it was handed. So
    a check over `SELECT DISTINCT court FROM cases` is the wrong denominator: measured
    2026-09-07 it reports 38 of 39 classifying and flags 'D.D.C.' twice, both of them
    healthy config-seeded rows (Common Cause v. DOJ, LWV v. DHS). An alarm shipped at
    that scope would have been born permanently red on correct data, which is the
    failure this section exists to prevent.

    WHY IT EXISTS. tracker_uw prints a WARN on an unmapped court and has done, four
    times a day, into a stderr nothing reads -- while two rows sat unresolved for
    seventeen days because UW spells the Eighth Circuit 'Eighth District' and the D.C.
    Circuit 'DC Circuit'. The aliases added in 6470a79 fix those two and nothing else:
    an alias exists only once someone has NOTICED the miss, and noticing is what
    failed. This turns the noticing into an exit code.

    TWO PREDICATES, and they are not the same one twice. `court_id` is normally
    `COURT_IDS.get(court)`, so a name that fails to classify usually arrives with a
    null id -- but the artifact is a committed file that can outlive an edit to the
    map. Removing an alias leaves a stale non-null id beside a name that no longer
    classifies, and checking only the id would miss it.

    Pure, taking rows rather than reading the file, because the suite must never read
    the live artifact -- the cron rewrites it, and a test pinned to it would fail for
    reasons that are not the test's subject. `main()` does the loading."""
    out = []
    for s in seeds:
        court = s.get("court")
        if court not in COURT_IDS or not s.get("court_id"):
            out.append(s)
    return out


def unmapped_state_statuses(rows) -> list:
    """Section 7: state bills whose NON-NULL status is outside 1-6. ALARM, expect 0.

    THE TRIPWIRE FOR THE ONE CASE STILL UNREACHABLE (ruled 2026-09-26). /state-bills
    holds a bill with no stage the ramp knows in an `unstaged` column, keyed after PA
    HR632 arrived with a null status on 2026-09-25. A NULL is keyed now: the page names
    it, assert-encodings.mjs checks it, and it does not fire here. A NON-NULL code
    outside 1-6 is different in kind -- LegiScan has given a status the page has no word
    for -- and the page would absorb it quietly, relabelling the column's header from
    "No status" to "No stage". That relabel is honest and it is silent, which is the
    failure this file exists to turn into an exit code: a new upstream vocabulary that
    nothing reads.

    Section 5's shape, one layer over: a name the map does not know, arriving from
    upstream, noticed only if something fails on it.

    Pure, taking rows, for section 5's reason: the suite must never read live data.
    `main()` does the SELECT, on whatever token audit.yml hands it (read-only)."""
    return [r for r in rows
            if r["status"] is not None and str(r["status"]) not in STATE_BILL_STATUSES]


def unbootstrapped(conn) -> list:
    """Section 6: rows never bootstrapped and linked to nothing. ALARM, expect 0.

    `entries_synced_at IS NULL` means no poll ever walked this docket. On its own that
    is not a defect: a terminated district row continued as a circuit appeal is
    COMPLETE, not unbootstrapped, and three such rows (PA 71453026, NH 71453646, MD
    71980724) have held a NULL mark since handoff 13 and always will. The alarm is the
    subset carrying no `superseded_by` -- never polled AND linked to nothing.

    Measured 2026-09-07: 0 with the clause, 3 without it, the three being exactly those
    orphans. That is the same shape as section 1 and the same trap: without the second
    clause the query reads 3 and every mention of it needs a caveat, which is how a
    standing check stops being run.

    This query is already written down -- docs/psephos.md carries it as the standing
    bootstrap-coverage check, to be pasted into a Turso shell by a human who remembers.
    Nobody remembered. Moving it here is the whole thesis of unit C: the query was
    correct, available and unrun, exactly like section 1's alarm and exactly like
    tracker_uw's WARN. The gap was never detection."""
    return conn.execute(
        "SELECT case_id, docket_number, court, status FROM cases "
        "WHERE entries_synced_at IS NULL AND superseded_by IS NULL "
        "ORDER BY case_id"
    ).fetchall()


# Section 8's bound, in hours; see the section's header above for the measurement.
COLLECT_SILENCE_MAX_HOURS = 24


def newest_channel_row(conn) -> str | None:
    """The newest `channel_runs.written_at` a collect.yml run wrote, or None when there is
    no such row or no table yet (created by the first collect run on the unit 99 build).
    Either None is a lane that has not written, and section 8 fires on it. A local run's
    rows (run_id 'local', or 'local.N') are not the lane and are skipped; GitHub's run ids
    are numeric."""
    try:
        return conn.execute("SELECT MAX(written_at) FROM channel_runs "
                            "WHERE run_id NOT LIKE 'local%'").fetchone()[0]
    except Exception as exc:  # noqa: BLE001 -- only the missing table is expected
        if "no such table" in str(exc).lower():
            return None
        raise


def collect_silence_hours(newest: str | None, now: datetime) -> float | None:
    """Hours since the newest row was written, None when there is no row. Pure, taking
    the value, for section 5's reason: the suite must never read live data."""
    if not newest:
        return None
    at = datetime.fromisoformat(str(newest).strip().replace("Z", "+00:00"))
    return (now - at.astimezone(timezone.utc)).total_seconds() / 3600


# A newest row stamped further ahead of now than this is a broken writer clock, not a
# live lane: ordinary skew between runners is seconds.
COLLECT_FUTURE_TOLERANCE_HOURS = 1


def lane_dead(hours: float | None) -> bool:
    """Section 8: ALARM, expect False. No row at all, none for longer than the bound, or
    a newest row stamped in the future."""
    return (hours is None or hours > COLLECT_SILENCE_MAX_HOURS
            or hours < -COLLECT_FUTURE_TOLERANCE_HOURS)


def main(argv=None) -> int:
    config.load_env()
    seeded = seeded_keys()
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT case_id, caption, court, docket_number, status, superseded_by "
            "FROM cases ORDER BY case_id").fetchall()
        held = {(r["docket_number"] or "").strip() for r in rows}
        unseeded = [r for r in rows if (r["docket_number"], r["court"]) not in seeded]
        alarm = unreconciled(rows, seeded)
        refs = unresolvable_refs(conn, held)
        watch = cert_watch(rows)
        drift = derived_drift(conn)
        artifact = load_tracker_seeds()
        unmapped = unclassified_courts(artifact)
        unbooted = unbootstrapped(conn)
        state_rows = conn.execute(
            "SELECT state_bill_id, state, bill_number, status FROM state_bills "
            "ORDER BY state_bill_id").fetchall()
        off_vocab = unmapped_state_statuses(state_rows)
        newest = newest_channel_row(conn)
        silence = collect_silence_hours(newest, datetime.now(timezone.utc))
        dead = lane_dead(silence)
        acks = load_acks()
        unack, blocked, lapsed = partition_alarm(alarm, acks, date.today())
        dangling = dangling_acks(alarm, acks)

        print(f"coverage_audit: {len(rows)} cases, {len(seeded)} seed keys "
              f"(union of config seed_cases + the tracker artifact)\n")

        print(f"  [1] RECONCILIATION ALARM -- unseeded and unlinked: {len(unack)}  (expect 0)")
        print(f"      {len(unseeded)} row(s) match no seed; the alarm is the subset of those")
        print("      with superseded_by IS NULL, i.e. polled by nothing and linked to nothing.")
        if acks:
            # The count above is the UNACKNOWLEDGED subset, and saying so here is not
            # decoration: a reader who sees 0 must be able to tell "nothing is wrong"
            # from "one thing is wrong and a person has ruled it unactionable".
            print(f"      {len(alarm)} row(s) fire; {len(blocked)} acknowledged-blocked and "
                  f"excluded from the count, {len(lapsed)} lapsed and counted.")
            print(f"      Register: {ACKS_PATH}. An acknowledgement, not a suppression --")
            print("      every row below still prints.")
        for r in unack:
            print(f"        FIRES  {r['case_id']:<10} {str(r['docket_number']):<16} "
                  f"{r['court']}  {r['caption'][:40]}")
        for r, a in blocked:
            print(f"        BLOCKED {r['case_id']:<9} {str(r['docket_number']):<16} "
                  f"{r['court']}  {r['caption'][:40]}")
            print(f"                 unblocks when: {a['unblocked_when']}   "
                  f"acknowledged {a['acknowledged_on']}, review by {a['review_by']}")
            # WRAPPED, NOT TRUNCATED. The reason is the whole content of an
            # acknowledgement -- a reader deciding whether it still holds needs all of
            # it, and a [:150] cut it mid-word inside "CourtListener" on the first
            # entry. Truncating the one field that justifies the suppression is how a
            # register starts being skimmed.
            for line in textwrap.wrap(" ".join(str(a["blocked_because"]).split()),
                                      width=92):
                print(f"                 {line}")
        for r, a, why in lapsed:
            # A lapsed row is back in the count and says why, or the register becomes a
            # thing that stops working quietly.
            print(f"        LAPSED {r['case_id']:<10} {str(r['docket_number']):<16} "
                  f"{r['court']}  {r['caption'][:40]}")
            print(f"                 {why} -- counted again")
        for a in dangling:
            print(f"        STALE ACK {a['case_id']} is not firing; entry has outlived "
                  f"its row (reported, not counted)")
        for r in unseeded:
            if r["superseded_by"] is not None:
                print(f"        ok     {r['case_id']:<10} {str(r['docket_number']):<16} "
                      f"-> {r['superseded_by']}  {r['court']}")

        print(f"\n  [2] UNRESOLVABLE DOCKET REFERENCES: {len(refs)} distinct  (a report, not an alarm)")
        print("      predecessor = we hold the appeal, not the case under it (seed + supersede forward)")
        print("      successor   = we hold the original, not what continued it (seed + supersede back)")
        print("      self-ref    = the naming row's own docket in another notation; noise, not a gap")
        print("      NOT MONOTONIC UNDER SEEDING: holding a docket removes its token AND adds that")
        print("      docket's own entries to the corpus, which can surface further references.")
        by_case = {r["case_id"]: r for r in rows}
        for tok, occ in sorted(refs.items()):
            named = sorted({c for c, _ in occ})
            kind = classify_ref(
                tok,
                [by_case[c]["court"] for c in named if c in by_case],
                [by_case[c]["docket_number"] for c in named if c in by_case],
            )
            print(f"        {tok:<18} x{len(occ):<3} {kind:<12} named by {','.join(named)}")
            print(f"            {occ[0][1][:150]}")

        print(f"\n  [3] CERT WATCH -- terminated circuit rows, no successor: {len(watch)}")
        for r in watch:
            print(f"        {r['case_id']:<10} {str(r['docket_number']):<16} "
                  f"{r['court']}  {r['caption'][:40]}")

        print(f"\n  [4] DERIVED-COLUMN ALARM -- latest_entry_at != MAX(record_entries.entry_at): "
              f"{len(drift)}  (expect 0)")
        for r in drift:
            print(f"        FIRES  {r['case_id']:<10} {str(r['docket_number']):<16} "
                  f"stored {str(r['stored'])[:10]} != derived {str(r['derived'])[:10]}  "
                  f"{r['court']}")

        print()
        print(f"  [5] VOCABULARY ALARM -- tracker courts that do not classify: "
              f"{len(unmapped)}  (expect 0)")
        print(f"      {len(artifact)} artifact row(s) checked against COURT_IDS "
              f"({len(COURT_IDS)} keys, aliases included). Config seeds are NOT in "
              f"scope: they carry a hand-authored court_id and never consult the map.")
        for s in unmapped:
            print(f"        FIRES  {str(s.get('state')):<16} court={s.get('court')!r} "
                  f"court_id={s.get('court_id')!r}  {s.get('docket_number')}")
            print(f"               add + verify its CourtListener id in "
                  f"collectors.tracker_uw.COURT_IDS")

        print()
        print(f"  [6] BOOTSTRAP ALARM -- never polled and linked to nothing: "
              f"{len(unbooted)}  (expect 0)")
        for r in unbooted:
            print(f"        FIRES  {r['case_id']:<10} {str(r['docket_number']):<16} "
                  f"{r['court']}  status={r['status']}")

        print()
        null_status = sum(1 for r in state_rows if r["status"] is None)
        print(f"  [7] STATUS VOCABULARY ALARM -- state bills with a non-null status outside "
              f"{STATE_BILL_STATUSES[0]}-{STATE_BILL_STATUSES[-1]}: {len(off_vocab)}  "
              f"(expect 0)")
        print(f"      {len(state_rows)} state bill(s) checked; {null_status} with a NULL "
              f"status, which is keyed on /state-bills and does not fire.")
        for r in off_vocab:
            print(f"        FIRES  {r['state_bill_id']:<10} status={r['status']!r}  "
                  f"{r['state']} {r['bill_number']}")
            print("               a LegiScan status the page has no word for: name it in "
                  "web/lib/statebill.ts and here, or rule it out")

        print()
        print(f"  [8] DEAD-LANE ALARM -- no collect run has written a channel_runs row for "
              f"over {COLLECT_SILENCE_MAX_HOURS}h: {int(dead)}  (expect 0)")
        if newest is None:
            print("        FIRES  channel_runs holds no collect-run row: no collect run on the "
                  "unit 99 build has reached its collectors")
        else:
            h, m = divmod(max(0, int(silence * 60)), 60)
            print(f"      newest collect-run row {newest}, {h}h{m:02d}m ago. The bound is the "
                  f"lane's longest gap in 368 runs, 23h07m, rounded up.")
            if silence < -COLLECT_FUTURE_TOLERANCE_HOURS:
                ah, am = divmod(int(-silence * 60), 60)
                print(f"        FIRES  the newest row is stamped {ah}h{am:02d}m AHEAD of now: "
                      f"a writer clock is wrong, and the row would hold this alarm off")
            elif dead:
                print(f"        FIRES  collect has written nothing for over {h}h{m:02d}m: read "
                      f"the collect.yml runs page -- disabled, not firing, or dying at setup")

        # A REPORT, NOT AN ALARM, and its failures stay out of the exit code with it:
        # a register the flags cannot read is assert-gates' to fail (exit 3, in ci.yml),
        # and this line says so rather than taking the six alarms and two reports above
        # down with it.
        print()
        try:
            gates = recheck_flags.load_gates()
            seeds = recheck_flags.load_seeds()
            for line in recheck_flags.report_lines(recheck_flags.compute(conn, gates, seeds),
                                                   recheck_flags.tally(gates, seeds)):
                print(line)
        except Exception as exc:  # noqa: BLE001 -- reported, never raised
            print(f"  [9] RECHECK FLAGS -- CANNOT RUN: {type(exc).__name__}: "
                  f"{' '.join(str(exc).split())[:300]}")

        # `unack`, not `alarm`: an acknowledged-blocked row is out of the exit
        # code and out of nothing else. A LAPSED entry is back in `unack` by way
        # of partition_alarm, so the expiry and the condition both reach here.
        return 1 if (unack or drift or unmapped or unbooted or off_vocab or dead) else 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

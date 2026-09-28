"""The collect run's verdict: turn the run red when a channel failed loudly (unit 99).

Invoked as a final step of `collect.yml` with `if: always()`, before the heartbeat. It
reads this run's `channel_runs` rows (written by the credentialed collectors through
`run_signals.RunSignals.flush`) and the three receipts, and exits 1 -- turning the run red
-- when any of these holds (Corey's rulings, 2026-09-28):

  * a LOUD row this run: credential failure, missing secret, no OK replies, cut short
    (R2, R3, R5, R6);
  * an expected channel wrote NO row: its collector never reached its flush, because it
    or an earlier line of the `bash -e` step died;
  * a RECEIPT is stale (R9): the channel has not reached its source for more expected
    slots than its threshold -- legislation `bills.updated_at`, litigation
    `cases.status_checked_at`, state its latest `ok` row;
  * a planned deferral outlived its channel's rotation (R6);
  * an earlier step of the job failed (R10: every red collect run comments).

It writes the comment body -- channel, class and evidence line per finding -- to
`$RUNNER_TEMP/collect-verdict.md`, which the issue step posts to the standing
`collect red` issue (R8). It WRITES NOTHING TO THE DATABASE, which is why it lives in
`tools/`, beside `coverage_audit`, the other scheduled read.

THE THRESHOLDS ARE MEASURED, NOT CHOSEN. Each is a count of missed expected slots, accepted
only if it stays silent across the channel's whole recorded history outside recorded
incidents, and would have caught the 2026-09-16 Congress.gov outage within one day (R9).
The history and the figures are in docs/status.md, *Unit 99*.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import db  # noqa: E402
import run_signals  # noqa: E402

STATE_SLOT = "17 6 * * *"          # collectors/state.py STATE_SLOT; pinned by a test
CREDENTIALED = ("legislation", "litigation", "state")

# R9: fire when the channel has missed MORE THAN this many expected slots in a row, the
# current run included. MEASURED 2026-09-28 over all 368 retained collect.yml logs and
# data/cases.json's history (docs/status.md, Unit 99):
#   legislation  scheduled runs; longest healthy gap 3 (08-06/07, the Turso 502), 1
#                otherwise. "More than 3" stays silent on all of it and fires on the 09-16
#                Congress.gov outage at its 4th failing run, 19h44m after the first.
#   litigation   scheduled runs; the receipt moves about daily, longest healthy gap 4
#                (08-11).
#   state        DAYS, by the clock, since its one slot a day may never fire and a slot
#                that never fired leaves no run row to count: every day with a state run
#                had an OK reply, and the one day without a run (07-08, every run red)
#                was never followed by a second. One missed day is tolerated because
#                GitHub drops about one slot in forty; a dead key is loud on the state
#                run itself (NO OK REPLIES or CREDENTIAL FAILURE), so this is the backstop
#                for state not running at all.
# A dispatch is not an expected slot, and neither is an earlier attempt of this run: both
# leave `runs` rows (the heartbeat writes every run, keyed without the attempt), and
# counting them turned a healthy litigation day red at two dispatches (review, 2026-09-28).
RECEIPT_MISSED_MAX = {"legislation": 3, "litigation": 4, "state": 1}
# A state slot counts as missed once this long past 06:17Z has gone by without a receipt:
# the lane's slot-to-commit lag reached 7h31m on 2026-09-28, and 12h leaves room.
STATE_SLOT_FAR_EDGE_HOURS = 12
# State's receipt is its latest `ok` row, or a run that its OWN ledger ceiling stopped
# before any request: proration is a planned deferral (R6), and at the ceiling every state
# slot takes that path until the month rolls over, so without this the receipt would go
# stale and the lane red four times a day for the rest of the month.
STATE_CEILING_EVIDENCE = "monthly ceiling reached"

# R6: a pending docket whose status was last read longer ago than the refresh period plus
# this has outlived the refresh rotation. The pass takes the oldest first (40 a run, 37
# pending at d0133a4) and runs once a day on the 20h gate, so a capped row is first in
# line at the next pass: older than 20h + 24h means a whole pass went by without it.
# History (data/cases.json, 122 snapshot commits since 2026-08-10): the oldest pending
# check reached 24.5h once, under the old 24h gate, and 19.9h since the 20h gate.
REFRESH_ROTATION_HOURS = 24
# State's getBill deferral and litigation's walk deferral print a DEFERRED line and are
# not checked here: neither queue has a rotation (both take items in list order, not
# oldest-deferred first), so "more runs than its rotation allows" has no figure. Recorded
# for a ruling in docs/status.md, Unit 99; a channel-level stand-in went red daily through
# a proration storm, which R6 names as planned.

FINDING_ORDER = ("job", "unrecorded", run_signals.MISSING, run_signals.CREDENTIAL,
                 run_signals.NO_OK, run_signals.CUT, "receipt stale", "rotation")


def normalize(raw: str) -> str:
    """An ISO timestamp in `common.now_iso()`'s shape, so string comparison is time order
    (`Z` sorts above `.`; see scripts/write_heartbeat.normalize)."""
    return datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00")).astimezone(
        timezone.utc).isoformat()


def expected_channels(slot: str) -> tuple[str, ...]:
    """State runs on its slot only (and on a dispatch or a local run)."""
    if slot in (STATE_SLOT, "dispatch", ""):
        return CREDENTIALED
    return ("legislation", "litigation")


def this_run_rows(conn, rid: str) -> list:
    return conn.execute(
        "SELECT channel, class, evidence FROM channel_runs WHERE run_id = ? "
        "ORDER BY channel, class", (rid,)).fetchall()


def runs_after(conn, since: str, this_run: str, slot: str | None = None) -> int:
    """Earlier SCHEDULED runs that started after `since`, optionally only those on
    `slot`. Not a dispatch, and not this run: the heartbeat has not written this attempt
    yet, but it wrote an earlier attempt's row under the same id."""
    sql = ("SELECT COUNT(*) FROM runs WHERE started_at > ? AND slot <> 'dispatch' "
           "AND run_id <> ?")
    args: tuple = (since, this_run)
    if slot is not None:
        sql += " AND slot = ?"
        args += (slot,)
    return int(conn.execute(sql, args).fetchone()[0])


def missed_slots(conn, receipt: str, started_at: str, slot_filter: str | None,
                 this_slot: str, this_run: str) -> int:
    """Expected slots missed since the receipt, this run included when it is a scheduled
    slot that is expected and the receipt predates it."""
    n = runs_after(conn, receipt, this_run, slot_filter)
    if (receipt < started_at and this_slot not in ("dispatch", "")
            and (slot_filter is None or this_slot == slot_filter)):
        n += 1
    return n


def state_slots_missed(receipt: datetime, now: datetime) -> int:
    """State slots (06:17Z daily) after the receipt whose far edge has passed. By the
    clock, not by run rows: a slot GitHub never fired leaves no row but is still missed."""
    slot = receipt.replace(hour=6, minute=17, second=0, microsecond=0)
    if slot <= receipt:
        slot += timedelta(days=1)
    n = 0
    while slot + timedelta(hours=STATE_SLOT_FAR_EDGE_HOURS) <= now:
        n += 1
        slot += timedelta(days=1)
    return n


def receipt_findings(conn, started_at: str, slot: str, now: datetime | None = None,
                     this_run: str = "") -> list[tuple[str, str, str]]:
    now = now or datetime.now(timezone.utc)
    out = []
    leg = conn.execute("SELECT MAX(updated_at) FROM bills").fetchone()[0]
    if leg:
        n = missed_slots(conn, normalize(leg), started_at, None, slot, this_run)
        if n > RECEIPT_MISSED_MAX["legislation"]:
            out.append(("legislation", "receipt stale",
                        f"bills.updated_at last moved {leg}; {n} scheduled runs since "
                        f"without it"))
    lit = conn.execute("SELECT MAX(status_checked_at) FROM cases").fetchone()[0]
    if lit:
        n = missed_slots(conn, normalize(lit), started_at, None, slot, this_run)
        if n > RECEIPT_MISSED_MAX["litigation"]:
            out.append(("litigation", "receipt stale",
                        f"cases.status_checked_at last moved {lit}; {n} scheduled runs "
                        f"since without it"))
    st = conn.execute("SELECT MAX(written_at) FROM channel_runs WHERE channel = 'state' "
                      "AND (class = 'ok' OR (class = 'deferred' AND evidence LIKE ?))",
                      (STATE_CEILING_EVIDENCE + "%",)).fetchone()[0]
    if st:
        n = state_slots_missed(datetime.fromisoformat(normalize(st)), now)
        if n > RECEIPT_MISSED_MAX["state"]:
            out.append(("state", "receipt stale",
                        f"last OK reply from LegiScan {st}; {n} state slots since without one"))
    return out


def rotation_findings(conn, now: datetime) -> list[tuple[str, str, str]]:
    out = []
    refresh_hours = config.load_sources()["litigation"].get("status_refresh_hours", 24)
    cutoff = (now - timedelta(hours=refresh_hours + REFRESH_ROTATION_HOURS)).isoformat()
    overdue = conn.execute(
        "SELECT COUNT(*) FROM cases WHERE (status IS NULL OR status <> 'terminated') "
        "AND status_checked_at IS NOT NULL AND status_checked_at < ?", (cutoff,)).fetchone()[0]
    if overdue:
        out.append(("litigation", "rotation",
                    f"{overdue} pending row(s) not status-checked for over "
                    f"{refresh_hours + REFRESH_ROTATION_HOURS}h (refresh period "
                    f"{refresh_hours}h plus the rotation's {REFRESH_ROTATION_HOURS}h)"))
    return out


def verdict(conn, rid: str, slot: str, started_at: str, job_status: str,
            now: datetime | None = None) -> list[tuple[str, str, str]]:
    """Every finding, as (channel, class, evidence). The run is red when this is non-empty."""
    now = now or datetime.now(timezone.utc)
    findings: list[tuple[str, str, str]] = []
    if job_status and job_status != "success":
        findings.append(("job", "job", f"an earlier step ended `{job_status}`"))
    rows = this_run_rows(conn, rid)
    seen = {r[0] for r in rows}
    for ch in expected_channels(slot):
        if ch not in seen:
            findings.append((ch, "unrecorded", "no channel_runs row this run: the collector "
                                               "did not reach its end (see the steps above)"))
    for ch, cls, ev in rows:
        if cls in run_signals.LOUD:
            findings.append((ch, cls, ev))
    # The heartbeat keys `runs` on GitHub's run id without the attempt.
    findings += receipt_findings(conn, started_at, slot, now, this_run=rid.split(".", 1)[0])
    findings += rotation_findings(conn, now)
    order = {c: i for i, c in enumerate(FINDING_ORDER)}
    return sorted(findings, key=lambda f: (order.get(f[1], 99), f[0]))


def body(findings, rid: str, slot: str, run_url: str) -> str:
    # The mention first, as the audit and dom-checks lanes open theirs: it notifies
    # whatever the watch status, where a bot comment alone reaches only watchers.
    lines = ["cc @CSU-J3", "",
             f"**collect red** -- run [{rid}]({run_url}), slot `{slot or 'dispatch'}`", "",
             "| channel | class | evidence |", "|---|---|---|"]
    for ch, cls, ev in findings:
        ev = (ev or "").replace("|", "\\|")
        lines.append(f"| {ch} | {cls} | {ev} |")
    lines += ["", "A person closes this issue against the first clean run (unit 99, R8)."]
    return "\n".join(lines) + "\n"


def _turso_secrets() -> tuple[str, ...]:
    """The database URL, its host alone, and the token: what a libsql error could echo."""
    url = os.environ.get("TURSO_DATABASE_URL") or ""
    host = url.split("://", 1)[-1].split("/", 1)[0].split("?", 1)[0]
    return tuple(s for s in (url, host, os.environ.get("TURSO_AUTH_TOKEN") or "") if s)


def main(argv=None) -> int:
    config.load_env()
    rid = run_signals.run_id()
    slot = os.environ.get("SLOT") or "dispatch"
    started_at = normalize(os.environ.get("RUN_STARTED_AT")
                           or datetime.now(timezone.utc).isoformat())
    job_status = os.environ.get("JOB_STATUS") or "unknown"
    run_url = os.environ.get("RUN_URL") or ""
    out = os.path.join(os.environ.get("RUNNER_TEMP") or ".", "collect-verdict.md")
    try:
        conn = db.connect()
    except Exception as exc:
        findings = [("job", "job", f"the verdict could not open the database: "
                                   f"{type(exc).__name__}")]
    else:
        try:
            findings = verdict(conn, rid, slot, started_at, job_status)
        except Exception as exc:
            # The type only, in the body: it goes to an issue, which GitHub does not mask,
            # and a libsql error can name the database URL, itself a secret here. The
            # message goes to the log, scrubbed of both Turso values.
            findings = [("job", "job", f"the verdict could not read the database: "
                                       f"{type(exc).__name__}")]
            print(f"collect verdict: database read failed -- "
                  f"{run_signals.scrub(str(exc), _turso_secrets())}", file=sys.stderr)
        finally:
            conn.close()
    if not findings:
        print(f"collect verdict: clean ({', '.join(expected_channels(slot))} recorded, "
              f"receipts fresh)")
        return 0
    text = body(findings, rid, slot, run_url)
    with open(out, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    print("collect verdict: RED")
    for ch, cls, ev in findings:
        print(f"  {ch}: {cls}: {ev}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

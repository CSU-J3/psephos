"""The collect run's verdict: turn the run red when a channel failed loudly (unit 99).

Invoked as a final step of `collect.yml` with `if: always()`, before the heartbeat. It
reads this run's `channel_runs` rows (written by every channel through
`run_signals.RunSignals.flush`, executive and news included since 2026-10-05) and the three
receipts, and exits 1 -- turning the run red -- when any of these holds (Corey's rulings,
2026-09-28, and 2026-10-05 for the crashes):

  * a LOUD row this run: credential failure, missing secret, no OK replies, cut short
    (R2, R3, R5, R6), or failed -- the collector raised, and `run_signals.guarded` wrote
    its exception line;
  * a part of the collectors step exited non-zero and left no `failed` row: named with its
    exit and its log's last line, which the step keeps for every part, since one part's
    crash no longer stops the others;
  * an expected channel wrote NO row and did not crash: its collector never reached its
    flush;
  * a RECEIPT is stale (R9): the channel has not reached its source for more expected
    slots than its threshold -- legislation `bills.updated_at`, litigation
    `cases.status_checked_at`, state its latest `ok` row;
  * a planned deferral outlived its channel's rotation (R6);
  * an earlier step of the job failed (R10: every red collect run comments), named, with
    the parts of the collectors step that failed or another step's last line where the
    step kept it (Corey, 2026-10-05, after a Turso drop in litigation was reported as "an
    earlier step ended failure" and went unread for a day and a half);
  * the data commit did not reach origin: the commit step writes
    `$RUNNER_TEMP/data-commit-not-pushed` first, retries a raced push, and clears the
    marker only when a push lands or nothing is left to push, so a step that gives up or
    dies mid-repair leaves it. It is named here as its own finding, with the evidence line
    "data commit not pushed" (Corey, 2026-09-30, after the 00:17Z slot's commit was lost
    to a human push and the verdict named only the step).

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
# State's receipt is its latest `ok` row and nothing else: it moves only when LegiScan
# answers (ruling 1b, Corey, 2026-09-28). A slot is EXCUSED from the missed-slot count by
# the `deferred` class: some state run between that slot and the next wrote `deferred`
# and no loud class. That run is the one its own ledger ceiling stopped before any request
# (proration, planned under R6), so a month at the ceiling stays quiet.
#  * Not a loud run: a share or mid-run ceiling deferral that follows a FAILED national
#    call also writes `deferred` with no `ok`, and its NO OK REPLIES makes it a miss.
#  * Any state run in the window, since channel_runs carries no slot: the slot's own, a
#    dispatch or a local one. Harmless: the ledger only grows within a month, so a run
#    that met the ceiling in the window means the slot's own run would have too.
#  * The slot's whole day, not its 12h far edge: a ceiling run landing late still excuses
#    its own slot rather than the next one's.
# Excused slots reset the count, as the old receipt did: RECEIPT_MISSED_MAX means misses
# IN A ROW, and two drops a fortnight apart in a ceiling month are not a dead lane.
# THE LIMIT, recorded: once the ceiling is hit, a key that dies mid-month is not seen
# until the next month's first state run, since no request is made to find out.
STATE_EXCUSED_CLASS = run_signals.DEFERRED

# R6: a pending docket whose status was last read longer ago than the refresh period plus
# this has outlived the refresh rotation. The pass takes the oldest first (40 a run, 37
# pending at d0133a4) and runs once a day on the 20h gate, so a capped row is first in
# line at the next pass: older than 20h + 24h means a whole pass went by without it.
# History (data/cases.json, 122 snapshot commits since 2026-08-10): the oldest pending
# check reached 24.5h once, under the old 24h gate, and 19.9h since the 20h gate.
REFRESH_ROTATION_HOURS = 24
# State's getBill deferral and litigation's walk deferral print a DEFERRED line and are
# not checked here: neither queue has a rotation (both take items in list order, not
# oldest-deferred first), so "more runs than its rotation allows" has no figure. RULED
# 2026-09-28 (1a, docs/status.md, Unit 99): the walk stays with coverage_audit section 6,
# and state's getBill queue goes oldest-deferred-first as its own unit before January
# 2027, after which this check gets a figure. A channel-level stand-in went red daily
# through a proration storm, which R6 names as planned.

# The commit step's marker (collect.yml, "Commit data changes"); read from RUNNER_TEMP.
DATA_COMMIT_MARKER = "data-commit-not-pushed"

FINDING_ORDER = ("job", "commit", run_signals.FAILED, "unrecorded", run_signals.MISSING,
                 run_signals.CREDENTIAL, run_signals.NO_OK, run_signals.CUT, "receipt stale",
                 "rotation")


def normalize(raw: str) -> str:
    """An ISO timestamp in `common.now_iso()`'s shape, so string comparison is time order
    (`Z` sorts above `.`; see scripts/write_heartbeat.normalize)."""
    return datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00")).astimezone(
        timezone.utc).isoformat()


def expected_channels(slot: str) -> tuple[str, ...]:
    """All five, on every slot (Corey, 2026-10-05): executive and news write their rows
    too, and state writes a quiet `skipped` row off its slot. `slot` is kept for callers."""
    return run_signals.CHANNELS


def channel_crashes(runner_temp: str | None) -> list[tuple[str, int, str]]:
    """(channel, exit code, last line of its log) for each part of the collectors step
    that exited non-zero, in run order: the step keeps each one's exit at
    $RUNNER_TEMP/channels and its output at $RUNNER_TEMP/channel-<name>.log."""
    tmp = runner_temp or "."
    out = []
    for ln in _read(os.path.join(tmp, "channels")).splitlines():
        name, _, code = ln.strip().partition(" ")
        if name and code.strip().lstrip("-").isdigit() and int(code) != 0:
            log = _read(os.path.join(tmp, f"channel-{name}.log"))
            out.append((name, int(code), last_line(log)))
    return out


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


def state_slots_due(receipt: datetime, now: datetime) -> list[datetime]:
    """State slots (06:17Z daily) after the receipt whose far edge has passed. By the
    clock, not by run rows: a slot GitHub never fired leaves no row but is still missed."""
    slot = receipt.replace(hour=6, minute=17, second=0, microsecond=0)
    if slot <= receipt:
        slot += timedelta(days=1)
    out = []
    while slot + timedelta(hours=STATE_SLOT_FAR_EDGE_HOURS) <= now:
        out.append(slot)
        slot += timedelta(days=1)
    return out


def state_slots_missed(receipt: datetime, now: datetime) -> int:
    return len(state_slots_due(receipt, now))


def state_slot_excused(conn, slot: datetime) -> bool:
    """Did a state run between this slot and the next write the excused class and no loud
    class (see STATE_EXCUSED_CLASS)?"""
    lo = slot.astimezone(timezone.utc).isoformat()
    hi = (slot + timedelta(days=1)).astimezone(timezone.utc).isoformat()
    loud = tuple(sorted(run_signals.LOUD))
    marks = ",".join("?" * len(loud))
    row = conn.execute(
        "SELECT COUNT(*) FROM channel_runs d WHERE d.channel = 'state' AND d.class = ? "
        "AND d.written_at >= ? AND d.written_at < ? AND NOT EXISTS ("
        "SELECT 1 FROM channel_runs l WHERE l.run_id = d.run_id AND l.channel = 'state' "
        f"AND l.class IN ({marks}))",
        (STATE_EXCUSED_CLASS, lo, hi, *loud)).fetchone()
    return bool(row[0])


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
                      "AND class = 'ok'").fetchone()[0]
    if st:
        due = state_slots_due(datetime.fromisoformat(normalize(st)), now)
        flags = [state_slot_excused(conn, s) for s in due]
        excused = sum(flags)
        # Misses IN A ROW: an excused slot resets the count, as the old receipt did.
        last = max((i for i, f in enumerate(flags) if f), default=-1)
        n = len(flags) - (last + 1)
        if n > RECEIPT_MISSED_MAX["state"]:
            out.append(("state", "receipt stale",
                        f"last OK reply from LegiScan {st}; {n} state slots in a row without "
                        f"one" + (f" (and {excused} excused since it: a planned deferral, "
                                  f"the ledger ceiling)" if excused else "")))
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


def data_commit_finding(runner_temp: str | None) -> list[tuple[str, str, str]]:
    """The commit step's marker, as a finding: its own line, never folded into a generic
    failed step. Its text begins "data commit not pushed"."""
    path = os.path.join(runner_temp or ".", DATA_COMMIT_MARKER)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        text = fh.read().strip() or "data commit not pushed"
    if not text.startswith("data commit not pushed"):
        text = f"data commit not pushed: {text}"
    return [("data", "commit", text)]


# THE STEP THAT FAILED, NAMED (Corey, 2026-10-05). The steps before the Verdict, by the id
# collect.yml gives each, in run order, with the name the run shows; STEP_OUTCOMES carries
# each one's outcome as `id=outcome` pairs. A step that keeps its output leaves it at
# $RUNNER_TEMP/<id>.log; the collectors step keeps each PART's, with its exit at
# $RUNNER_TEMP/channels (see channel_crashes). Pinned to collect.yml by
# tests/test_collect_failed_step.py.
STEPS = (("checkout", "actions/checkout@v4"), ("python", "actions/setup-python@v5"),
         ("deps", "Install dependencies"), ("collectors", "Run collectors"),
         ("export", "Export JSON snapshots"), ("commit", "Commit data changes"))


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def last_line(text: str) -> str:
    """The output's last non-empty line: for a Python failure, its exception, which the
    interpreter prints after every line a `finally` block wrote."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def failed_step(step_outcomes: str | None, runner_temp: str | None) -> str | None:
    """The first step before the Verdict that failed, named: the collectors step with the
    parts that exited non-zero, whose lines are their own findings; another step with its
    last line where it kept its output. None when STEP_OUTCOMES names no failure."""
    outcomes = dict(pair.split("=", 1) for pair in (step_outcomes or "").split() if "=" in pair)
    tmp = runner_temp or "."
    for sid, name in STEPS:
        if outcomes.get(sid) != "failure":
            continue
        crashed = [c for c, _, _ in channel_crashes(runner_temp)] if sid == "collectors" else []
        if crashed:
            return f"`{name}` failed: {', '.join(crashed)} exited non-zero"
        line = last_line(_read(os.path.join(tmp, f"{sid}.log")))
        return f"`{name}` failed: {line}" if line else f"`{name}` failed; its output is in the run's log"
    return None


def job_findings(job_status: str, step_outcomes: str | None = None,
                 runner_temp: str | None = None) -> list[tuple[str, str, str]]:
    """The job's own finding when it is not green: the step that failed, named, or the
    status alone when no outcome names a failed step."""
    if not job_status or job_status == "success":
        return []
    return [("job", "job", failed_step(step_outcomes, runner_temp)
             or f"an earlier step ended `{job_status}`")]


def verdict(conn, rid: str, slot: str, started_at: str, job_status: str,
            now: datetime | None = None,
            runner_temp: str | None = None,
            step_outcomes: str | None = None) -> list[tuple[str, str, str]]:
    """Every finding, as (channel, class, evidence). The run is red when this is non-empty."""
    now = now or datetime.now(timezone.utc)
    findings: list[tuple[str, str, str]] = job_findings(job_status, step_outcomes, runner_temp)
    findings += data_commit_finding(runner_temp)
    rows = this_run_rows(conn, rid)
    seen = {r[0] for r in rows}
    # A channel that crashed is named by its own `failed` row when it could write one, and
    # otherwise by the step's record of its exit and its log's last line -- never also as
    # "unrecorded", which says less.
    failed_rows = {r[0] for r in rows if r[1] == run_signals.FAILED}
    crashed = set()
    for ch, code, line in channel_crashes(runner_temp):
        crashed.add(ch)
        if ch not in failed_rows:
            findings.append((ch, run_signals.FAILED,
                             f"exited {code}: {line}" if line else f"exited {code}"))
    for ch in expected_channels(slot):
        if ch not in seen and ch not in crashed:
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


def scrubbed(findings) -> list[tuple[str, str, str]]:
    """Every evidence line scrubbed again, here, of every credential in this step's
    environment and every URL's query string (ruling 2a). Actions masks secrets in the
    run log, not in text a step sends to the Issues API, so the comment cannot lean on the
    mask. The rows were scrubbed when the collectors wrote them; this holds for a row any
    other writer left, and for the verdict's own findings."""
    secrets = run_signals.env_secrets()
    return [(ch, cls, run_signals.scrub(ev or "", secrets)) for ch, cls, ev in findings]


def body(findings, rid: str, slot: str, run_url: str) -> str:
    # The mention first, as the audit and dom-checks lanes open theirs: it notifies
    # whatever the watch status, where a bot comment alone reaches only watchers.
    lines = ["cc @CSU-J3", "",
             f"**collect red** -- run [{rid}]({run_url}), slot `{slot or 'dispatch'}`", "",
             "| channel | class | evidence |", "|---|---|---|"]
    for ch, cls, ev in scrubbed(findings):
        ev = ev.replace("|", "\\|")
        lines.append(f"| {ch} | {cls} | {ev} |")
    lines += ["", "A person closes this issue against the first clean run (unit 99, R8)."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    config.load_env()
    rid = run_signals.run_id()
    slot = os.environ.get("SLOT") or "dispatch"
    started_at = normalize(os.environ.get("RUN_STARTED_AT")
                           or datetime.now(timezone.utc).isoformat())
    job_status = os.environ.get("JOB_STATUS") or "unknown"
    step_outcomes = os.environ.get("STEP_OUTCOMES")
    run_url = os.environ.get("RUN_URL") or ""
    runner_temp = os.environ.get("RUNNER_TEMP")
    out = os.path.join(runner_temp or ".", "collect-verdict.md")
    try:
        conn = db.connect()
    except Exception as exc:
        findings = (job_findings(job_status, step_outcomes, runner_temp)
                    + [("job", "job", f"the verdict could not open the database: "
                                      f"{type(exc).__name__}")] + data_commit_finding(runner_temp))
    else:
        try:
            findings = verdict(conn, rid, slot, started_at, job_status,
                               runner_temp=runner_temp, step_outcomes=step_outcomes)
        except Exception as exc:
            # The type only, in the body: it goes to an issue, which GitHub does not mask,
            # and a libsql error can name the database URL, itself a secret here. The
            # message goes to the log, scrubbed of every credential in the environment.
            findings = (job_findings(job_status, step_outcomes, runner_temp)
                        + [("job", "job", f"the verdict could not read the database: "
                                          f"{type(exc).__name__}")] + data_commit_finding(runner_temp))
            print(f"collect verdict: database read failed -- "
                  f"{run_signals.scrub(str(exc), run_signals.env_secrets())}",
                  file=sys.stderr)
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
    for ch, cls, ev in scrubbed(findings):
        print(f"  {ch}: {cls}: {ev}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

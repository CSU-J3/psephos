"""Unit 99: the loud line, the channel_runs row, the verdict that reads it, and the
workflow steps that carry it to the standing issue -- joined.

WHY THIS EXISTS. The Congress.gov key sat disabled for 33 scheduled runs and every one
concluded `success`. Unit 99 keeps each collector's exit 0 and moves the alarm to three
places that live in three files: `run_signals.py` prints the line and writes the row,
`tools/collect_verdict.py` reads the rows and the receipts and exits 1, and
`.github/workflows/collect.yml` runs the verdict and posts its body. A prose comment in
any of them cannot fail, and deleting `if: always()` from the verdict, or a threshold
drifting by one, would break nothing any collector test can see.

Offline and deterministic: a temp SQLite database with schema.sql applied, rows inserted
directly, no network, no `.env`. `main()` IS exercised here, unlike coverage_audit's
suite, because `config.load_env` and `db.connect` are both replaced before it runs, so it
can never reach the remote. Every secret is an obvious fixture string.

Run:  pytest tests/test_unit99_verdict.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.chdir(REPO)  # config.load_sources / db.init_db use repo-relative paths

import pytest  # noqa: E402
import yaml  # noqa: E402

import common  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import run_signals as rs  # noqa: E402
from collectors import state  # noqa: E402
from tools import collect_verdict as cv  # noqa: E402

UTC = timezone.utc
SCHEMA = str(REPO / "schema.sql")
KEY = "FIXTUREKEY-0123456789abcdef"
TOKEN = "FIXTURETOKEN-fedcba9876543210"
FIXTURE_VAR = "PSEPHOS_UNIT99_FIXTURE_SECRET"
RID = "unit99-fixture-run"
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
STARTED = "2026-09-28T11:30:00+00:00"
DURING = "2026-09-28T11:40:00+00:00"
GETBILL_DEFERRAL = ("12 changed bill(s) deferred, getBill budget spent; they resume next "
                    "state run")


@pytest.fixture
def live(tmp_path):
    path = str(tmp_path / "t.db")
    db.init_db(path, schema=SCHEMA)
    conn = db.connect(path)
    yield conn
    conn.close()


def _channel_row(conn, rid, channel, cls, evidence="", written_at=DURING):
    conn.execute(
        "INSERT INTO channel_runs (run_id, channel, class, evidence, written_at) "
        "VALUES (?,?,?,?,?)", (rid, channel, cls, evidence, written_at))


def _run(conn, rid, started_at, slot="17 0 * * *"):
    conn.execute(
        "INSERT INTO runs (run_id, slot, started_at, finished_at, items_written, conclusion) "
        "VALUES (?,?,?,?,0,'success')", (rid, slot, started_at, started_at))


def _bill(conn, updated_at):
    conn.execute(
        "INSERT INTO bills (bill_id, congress, bill_type, number, updated_at) "
        "VALUES ('hr22-119', 119, 'hr', 22, ?)", (updated_at,))


def _case(conn, case_id, status, checked_at):
    conn.execute(
        "INSERT INTO cases (case_id, caption, status, status_checked_at) VALUES (?,?,?,?)",
        (case_id, f"United States v. Fixture {case_id}", status, checked_at))


def _fresh(conn, with_state=False):
    """This run recorded legislation and litigation (and state if asked), and both
    receipts moved during it: the clean baseline every red test mutates one thing of."""
    _channel_row(conn, RID, "legislation", rs.OK, "6 OK replies")
    _channel_row(conn, RID, "litigation", rs.OK, "40 OK replies")
    if with_state:
        _channel_row(conn, RID, "state", rs.OK, "18 OK replies")
    _bill(conn, DURING)
    _case(conn, "72347022", "pending", DURING)
    conn.commit()


def _kinds(findings):
    return [(ch, cls) for ch, cls, _ in findings]


# --- run_signals: the line and the row ---------------------------------------------


def test_the_loud_classes_are_exactly_the_middle_four():
    assert rs.CLASSES == (rs.OK, rs.CREDENTIAL, rs.MISSING, rs.NO_OK, rs.CUT, rs.DEFERRED,
                          rs.UNREACHED)
    assert rs.LOUD == {"credential failure", "missing secret", "no OK replies", "cut short"}


def test_each_class_prints_its_literal_line_once(capsys):
    """The first note of a class prints and keeps its evidence; a second note of the
    same class only counts. Six refusals are one line, not six."""
    sig = rs.RunSignals("legislation", secrets=(KEY,))
    sig.note(rs.CREDENTIAL, "API_KEY_INVALID (HTTP 403)")
    sig.note(rs.CREDENTIAL, "a second refusal")
    sig.note(rs.CUT, "OVER_RATE_LIMIT (HTTP 429)")
    sig.note(rs.CUT, "again")
    sig.note(rs.NO_OK)
    sig.note(rs.DEFERRED, "walk budget spent")
    assert capsys.readouterr().out.splitlines() == [
        "CREDENTIAL FAILURE legislation: API_KEY_INVALID (HTTP 403)",
        "RUN CUT SHORT legislation: OVER_RATE_LIMIT (HTTP 429)",
        "NO OK REPLIES legislation",
        "DEFERRED legislation: walk budget spent",
    ]
    assert sig.counts == {rs.CREDENTIAL: 2, rs.CUT: 2, rs.NO_OK: 1, rs.DEFERRED: 1}
    assert sig.notes[rs.CREDENTIAL] == "API_KEY_INVALID (HTTP 403)"
    assert sig.loud()


def test_a_missing_secret_prints_the_credential_line_and_keeps_its_own_class(capsys):
    sig = rs.RunSignals("state")
    sig.note(rs.MISSING, "LEGISCAN_API_KEY is empty; channel skipped")
    assert capsys.readouterr().out == (
        "CREDENTIAL FAILURE state: LEGISCAN_API_KEY is empty; channel skipped\n")
    assert sig.has(rs.MISSING) and not sig.has(rs.CREDENTIAL)


def test_ok_is_not_noted_it_comes_from_reached():
    with pytest.raises(ValueError):
        rs.RunSignals("state").note(rs.OK, "")


def test_evidence_is_scrubbed_of_every_secret_value(capsys):
    """A quoted body is printed; a server echoing the key must not put it in the log."""
    sig = rs.RunSignals("litigation", secrets=(KEY, TOKEN, ""))
    sig.note(rs.CREDENTIAL, f'{{"detail": "Invalid token {TOKEN}"}} '
                            f"url=https://x.invalid/?api_key={KEY}&again={KEY}")
    out = capsys.readouterr().out
    assert KEY not in out and TOKEN not in out
    # The body's token redacted; the URL's query string dropped whole (ruling 2a).
    assert out == ('CREDENTIAL FAILURE litigation: {"detail": "Invalid token [redacted]"} '
                   'url=https://x.invalid/\n')
    assert KEY not in sig.notes[rs.CREDENTIAL] and TOKEN not in sig.notes[rs.CREDENTIAL]


def test_an_empty_secret_redacts_nothing():
    """str.replace('', x) interleaves x between every character; the guard is load-bearing."""
    assert rs.scrub("abc", secrets=("",)) == "abc"


def test_evidence_collapses_whitespace_and_truncates_at_300():
    assert rs.EVIDENCE_MAX == 300
    long = rs.scrub("x" * 1000)
    assert len(long) == 300 and long.endswith("...")
    assert rs.scrub("x" * 300) == "x" * 300
    assert rs.scrub("a\n\t   b  ") == "a b"


def test_redaction_runs_before_truncation_so_no_key_prefix_survives():
    cut = rs.scrub("y" * 295 + KEY, secrets=(KEY,))
    assert len(cut) == 300
    assert "FIXTURE" not in cut


def test_a_noted_line_is_truncated_too(capsys):
    rs.RunSignals("legislation").note(rs.CUT, "z" * 1000)
    line = capsys.readouterr().out.rstrip("\n")
    assert line == "RUN CUT SHORT legislation: " + "z" * 297 + "..."


def test_quote_scrubs_and_wraps_in_double_quotes():
    assert rs.quote(f'say "no" to {KEY}', (KEY,)) == "\"say 'no' to [redacted]\""


def test_run_id_is_githubs_or_local(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "4242")
    assert rs.run_id() == "4242"
    monkeypatch.delenv("GITHUB_RUN_ID")
    assert rs.run_id() == "local"


def test_run_id_carries_the_attempt_from_the_second_on(monkeypatch):
    """A re-run reuses the run id and the rows are keyed per class, so a clean second
    attempt would otherwise find the first attempt's loud rows and read red."""
    monkeypatch.setenv("GITHUB_RUN_ID", "4242")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    assert rs.run_id() == "4242"
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    assert rs.run_id() == "4242.2"


def test_secret_is_empty_rather_than_an_exit_when_the_variable_is_missing(monkeypatch):
    """R5: a missing secret skips its channel; config.require_env's SystemExit would end
    the whole `bash -e` step and every channel after it."""
    monkeypatch.delenv(FIXTURE_VAR, raising=False)
    assert rs.secret(FIXTURE_VAR) == ""
    monkeypatch.setenv(FIXTURE_VAR, "")
    assert rs.secret(FIXTURE_VAR) == ""
    monkeypatch.setenv(FIXTURE_VAR, KEY)
    assert rs.secret(FIXTURE_VAR) == KEY


def test_flush_writes_one_row_per_class_and_ok_only_when_reached(live, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_RUN_ID", "4242")

    refused = rs.RunSignals("legislation", secrets=(KEY,))
    refused.note(rs.CREDENTIAL, f"API_KEY_INVALID {KEY} (HTTP 403)")
    assert refused.flush(live) is True
    rows = live.execute("SELECT run_id, channel, class, evidence, written_at "
                        "FROM channel_runs").fetchall()
    assert [tuple(r)[:4] for r in rows] == [
        ("4242", "legislation", "credential failure", "API_KEY_INVALID [redacted] (HTTP 403)")]
    assert rows[0][4], "written_at is stamped"

    reached = rs.RunSignals("state")
    reached.note(rs.DEFERRED, GETBILL_DEFERRAL)
    reached.reached(2)
    assert reached.flush(live) is True
    assert reached.flush(live) is True  # keyed (run_id, channel, class): replaces
    got = live.execute("SELECT class, evidence FROM channel_runs WHERE channel = 'state' "
                       "ORDER BY class").fetchall()
    assert [tuple(r) for r in got] == [("deferred", GETBILL_DEFERRAL), ("ok", "2 OK replies")]

    one = rs.RunSignals("litigation")
    one.reached()
    one.flush(live)
    assert live.execute("SELECT evidence FROM channel_runs WHERE channel = 'litigation'"
                        ).fetchone()[0] == "1 OK reply"
    capsys.readouterr()


def test_a_channel_that_met_nothing_and_reached_nothing_writes_unreached_and_stays_quiet(
        live, monkeypatch):
    """Every request failed some quiet way (a 5xx run, a transport outage): the row says
    the collector ENDED, so the verdict does not read a dead collector (`unrecorded`), and
    the receipt governs the channel (R9) -- here one run old, so the run is clean."""
    monkeypatch.setenv("GITHUB_RUN_ID", RID)
    assert rs.RunSignals("legislation").flush(live) is True
    assert [tuple(r) for r in live.execute(
        "SELECT channel, class FROM channel_runs").fetchall()] == [("legislation", rs.UNREACHED)]
    assert rs.UNREACHED not in rs.LOUD
    _channel_row(live, RID, "litigation", rs.OK, "40 OK replies")
    _bill(live, "2026-09-28T05:40:00+00:00")
    _case(live, "72347022", "pending", DURING)
    live.commit()
    assert cv.verdict(live, RID, "17 0 * * *", STARTED, "success", NOW) == []


def test_a_flush_whose_recover_also_raises_still_returns_false(monkeypatch, capsys):
    """flush() runs at the end of every run: if recover() raised through it (a remote
    reopen that exhausts its ladder), a clean run would exit non-zero and end the step."""

    class Dead:
        def execute(self, *a, **k):
            raise RuntimeError("stream not found")

        def commit(self):
            raise AssertionError("commit is never reached")

    def recover(conn):
        raise RuntimeError("reopen failed after retries")

    monkeypatch.setattr(rs.db, "recover", recover)
    sig = rs.RunSignals("legislation")
    sig.note(rs.CREDENTIAL, "API_KEY_INVALID (HTTP 403)")
    assert sig.flush(Dead()) is False
    assert "channel_runs write failed" in capsys.readouterr().err


def test_a_failed_flush_returns_false_scrubbed_and_does_not_raise(capsys):
    """The collector keeps its exit 0 even when the row cannot be written; the verdict
    reads the missing row as `unrecorded`."""

    class RefusingConn:
        rolled_back = False

        def execute(self, *a, **k):
            raise RuntimeError(f"stream not found near {KEY}")

        def commit(self):
            raise AssertionError("commit is never reached")

        def rollback(self):
            self.rolled_back = True

    conn = RefusingConn()
    sig = rs.RunSignals("legislation", secrets=(KEY,))
    sig.note(rs.CREDENTIAL, "API_KEY_INVALID (HTTP 403)")
    assert sig.flush(conn) is False
    assert conn.rolled_back
    err = capsys.readouterr().err
    assert "channel_runs write failed" in err and KEY not in err


# --- the verdict: rows this run -------------------------------------------------------


def test_a_clean_run_has_no_findings(live):
    _fresh(live, with_state=True)
    assert cv.verdict(live, RID, cv.STATE_SLOT, STARTED, "success", NOW) == []


@pytest.mark.parametrize("slot, state_expected", [
    ("17 6 * * *", True), ("dispatch", True), ("", True),
    ("17 0 * * *", False), ("17 12 * * *", False), ("17 18 * * *", False),
])
def test_state_is_expected_only_on_its_slot_a_dispatch_or_a_local_run(live, slot, state_expected):
    _fresh(live)
    got = cv.verdict(live, RID, slot, STARTED, "success", NOW)
    assert _kinds(got) == ([("state", "unrecorded")] if state_expected else [])


def test_an_expected_channel_with_no_row_is_unrecorded(live):
    _channel_row(live, RID, "litigation", rs.OK, "40 OK replies")
    _bill(live, DURING)
    live.commit()
    assert _kinds(cv.verdict(live, RID, "17 0 * * *", STARTED, "success", NOW)) == [
        ("legislation", "unrecorded")]


@pytest.mark.parametrize("cls", rs.CLASSES)
def test_every_loud_row_turns_the_run_red_and_no_quiet_one_does(live, cls):
    _fresh(live)
    if cls != rs.OK:
        _channel_row(live, RID, "legislation", cls, "evidence for " + cls)
        live.commit()
    got = cv.verdict(live, RID, "17 0 * * *", STARTED, "success", NOW)
    if cls in rs.LOUD:
        assert got == [("legislation", cls, "evidence for " + cls)]
    else:
        assert got == []


def test_a_loud_row_from_another_run_is_not_this_runs_finding(live):
    _fresh(live)
    _channel_row(live, "an-earlier-run", "legislation", rs.CREDENTIAL, "API_KEY_INVALID")
    live.commit()
    assert cv.verdict(live, RID, "17 0 * * *", STARTED, "success", NOW) == []


@pytest.mark.parametrize("job_status", ["failure", "cancelled"])
def test_a_failed_earlier_step_is_red_on_its_own(live, job_status):
    _fresh(live)
    got = cv.verdict(live, RID, "17 0 * * *", STARTED, job_status, NOW)
    assert got == [("job", "job", f"an earlier step ended `{job_status}`")]


# --- receipts (R9) ---------------------------------------------------------------------


def test_the_receipt_thresholds_are_the_measured_ones():
    assert cv.RECEIPT_MISSED_MAX == {"legislation": 3, "litigation": 4, "state": 1}
    assert cv.STATE_SLOT_FAR_EDGE_HOURS == 12


def _missed_runs(conn, receipt: datetime, missed: int) -> str:
    """Runs rows for `missed - 1` earlier runs after the receipt, plus one before it that
    must not count; returns this run's start, the `missed`th slot after the receipt."""
    _run(conn, "before-the-receipt", (receipt - timedelta(hours=6)).isoformat())
    for i in range(missed - 1):
        _run(conn, f"earlier-{i}", (receipt + timedelta(hours=6 * (i + 1))).isoformat())
    conn.commit()
    return (receipt + timedelta(hours=6 * missed)).isoformat()


@pytest.mark.parametrize("missed, fires", [(3, False), (4, True)])
def test_legislation_receipt_fires_at_four_missed_runs_not_three(live, missed, fires):
    receipt = datetime(2026, 9, 27, 0, 30, tzinfo=UTC)
    _bill(live, receipt.isoformat())
    started = _missed_runs(live, receipt, missed)
    got = cv.receipt_findings(live, started, "17 0 * * *", NOW)
    expected = [("legislation", "receipt stale",
                 f"bills.updated_at last moved {receipt.isoformat()}; "
                 f"{missed} scheduled runs since without it")]
    assert got == (expected if fires else [])


@pytest.mark.parametrize("missed, fires", [(4, False), (5, True)])
def test_litigation_receipt_fires_at_five_missed_runs_not_four(live, missed, fires):
    receipt = datetime(2026, 9, 27, 0, 30, tzinfo=UTC)
    _case(live, "72347022", "terminated", receipt.isoformat())
    started = _missed_runs(live, receipt, missed)
    got = cv.receipt_findings(live, started, "17 0 * * *", NOW)
    expected = [("litigation", "receipt stale",
                 f"cases.status_checked_at last moved {receipt.isoformat()}; "
                 f"{missed} scheduled runs since without it")]
    assert got == (expected if fires else [])


def test_dispatches_and_this_runs_earlier_attempt_are_not_missed_slots(live):
    """R9 counts missed EXPECTED slots. A dispatch is not one, from any branch, and the
    heartbeat's row for this run's first attempt is this run, not an earlier slot. The
    review's case: litigation's receipt is a day old by design, so two dispatches inside
    it read 5 and went red on a healthy channel."""
    receipt = datetime(2026, 9, 27, 0, 30, tzinfo=UTC)
    _case(live, "72347022", "pending", receipt.isoformat())
    started = _missed_runs(live, receipt, 4)               # three scheduled runs, then this
    _run(live, "a-dispatch", (receipt + timedelta(hours=7)).isoformat(), slot="dispatch")
    _run(live, "another", (receipt + timedelta(hours=8)).isoformat(), slot="dispatch")
    _run(live, "4242", (receipt + timedelta(hours=23)).isoformat())  # attempt 1 of this run
    live.commit()
    assert cv.receipt_findings(live, started, "17 0 * * *", NOW, this_run="4242") == []
    # Counted raw, the same rows read six earlier runs: the fault the review measured.
    assert live.execute("SELECT COUNT(*) FROM runs WHERE started_at > ?",
                        (receipt.isoformat(),)).fetchone()[0] == 6
    # One more SCHEDULED run does fire: the exclusions narrow the count, not the alarm.
    _run(live, "earlier-3", (receipt + timedelta(hours=22)).isoformat())
    live.commit()
    assert _kinds(cv.receipt_findings(live, started, "17 0 * * *", NOW, this_run="4242")) == [
        ("litigation", "receipt stale")]


def test_a_dispatch_is_not_itself_a_missed_slot(live):
    receipt = datetime(2026, 9, 27, 0, 30, tzinfo=UTC)
    started = _missed_runs(live, receipt, 5)
    assert cv.missed_slots(live, receipt.isoformat(), started, None, "17 0 * * *", "x") == 5
    assert cv.missed_slots(live, receipt.isoformat(), started, None, "dispatch", "x") == 4


def test_the_verdict_passes_this_runs_id_without_the_attempt(live, monkeypatch):
    """verdict() takes run_signals.run_id(), `4242.2` on a re-run; the heartbeat keyed the
    first attempt's row as `4242`, and that row must not count as a missed slot."""
    seen = {}

    def spy(conn, started_at, slot, now=None, this_run=""):
        seen["this_run"] = this_run
        return []

    monkeypatch.setattr(cv, "receipt_findings", spy)
    cv.verdict(live, "4242.2", "17 0 * * *", STARTED, "success", NOW)
    assert seen["this_run"] == "4242"


@pytest.mark.parametrize("now, missed", [
    (datetime(2026, 9, 22, 18, 16, tzinfo=UTC), 1),   # second slot's far edge 1 min away
    (datetime(2026, 9, 22, 18, 17, tzinfo=UTC), 2),   # ... and now passed
])
def test_state_receipt_fires_by_the_clock_when_two_far_edges_have_passed(live, now, missed):
    """No runs rows at all: a state slot GitHub never fired leaves none, and is still
    missed. Receipt after the 09-20 slot; next slots 09-21 and 09-22 06:17, far edges
    +12h."""
    receipt = "2026-09-20T07:00:00+00:00"
    _channel_row(live, "state-run", "state", rs.OK, "1 OK reply", receipt)
    live.commit()
    assert cv.state_slots_missed(datetime.fromisoformat(receipt), now) == missed
    got = cv.receipt_findings(live, now.isoformat(), cv.STATE_SLOT, now)
    if missed > 1:
        assert got == [("state", "receipt stale",
                        f"last OK reply from LegiScan {receipt}; {missed} state slots in a "
                        f"row without one")]
    else:
        assert got == []


# --- rotation (R6) ---------------------------------------------------------------------


def _rotation_window() -> timedelta:
    refresh = config.load_sources()["litigation"].get("status_refresh_hours", 24)
    return timedelta(hours=refresh + cv.REFRESH_ROTATION_HOURS)


@pytest.mark.parametrize("status, fires", [
    ("pending", True), (None, True), ("terminated", False)])
def test_a_pending_case_past_refresh_plus_24h_fires_a_terminated_one_does_not(live, status, fires):
    _case(live, "just-inside", "pending", (NOW - _rotation_window() + timedelta(minutes=1)).isoformat())
    _case(live, "old", status, (NOW - _rotation_window() - timedelta(minutes=1)).isoformat())
    live.commit()
    got = [f for f in cv.rotation_findings(live, NOW) if f[0] == "litigation"]
    assert _kinds(got) == ([("litigation", "rotation")] if fires else [])
    if fires:
        assert got[0][2].startswith("1 pending row(s)")


def _state_run(conn, rid, day, deferral):
    at = f"2026-09-{day:02d}T10:00:00+00:00"
    _channel_row(conn, rid, "state", rs.OK, "18 OK replies", at)
    if deferral:
        _channel_row(conn, rid, "state", rs.DEFERRED, deferral, at)


def test_a_proration_storm_of_getbill_deferrals_stays_quiet(live):
    """R6 names proration a planned deferral, never loud. The getBill queue has no
    rotation to measure a starving bill against (it takes bills in master-list order), so
    the verdict does not guess one: a channel-level stand-in went red daily through a
    storm like this, which is a queue draining as designed. Recorded for a ruling."""
    for i, day in enumerate(range(20, 28)):
        _state_run(live, f"s{i}", day, GETBILL_DEFERRAL)
    live.commit()
    assert cv.rotation_findings(live, NOW) == []
    assert not hasattr(cv, "STATE_DEFER_RUNS_MAX")


CEILING = "monthly ceiling reached (used 8000 of 8000); no request made this run"


def test_the_ceiling_does_not_move_the_receipt_but_excuses_its_slots(live):
    """Ruling 1b: the receipt moves only when LegiScan answers. A state slot whose run
    wrote `deferred` -- only a ceiling-stopped run writes it without `ok` -- is excused,
    so a month at the ceiling stays quiet; a slot with no state row at all is not."""
    _channel_row(live, "old-ok", "state", rs.OK, "18 OK replies", "2026-09-20T10:00:00+00:00")
    for day in range(21, 26):                  # five ceiling days, 09-21 .. 09-25
        _channel_row(live, f"ceiling-{day}", "state", rs.DEFERRED, CEILING,
                     f"2026-09-{day:02d}T13:00:00+00:00")
    live.commit()
    # 09-26 12:00: five slots due, all excused.
    now = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
    assert cv.receipt_findings(live, now.isoformat(), cv.STATE_SLOT, now) == []
    # 09-27 12:00: the 09-26 slot passed its far edge with no state row -- one unexcused.
    now = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    assert cv.receipt_findings(live, now.isoformat(), cv.STATE_SLOT, now) == []
    # 09-27 19:00: the 09-27 slot too -- two unexcused, and the receipt still names the
    # last OK reply.
    now = datetime(2026, 9, 27, 19, 0, tzinfo=UTC)
    assert cv.receipt_findings(live, now.isoformat(), cv.STATE_SLOT, now) == [
        ("state", "receipt stale",
         "last OK reply from LegiScan 2026-09-20T10:00:00+00:00; 2 state slots in a row "
         "without one (and 5 excused since it: a planned deferral, the ledger ceiling)")]


def test_drops_apart_in_a_ceiling_month_stay_quiet(live):
    """The review's case: the receipt stays at the last OK for the whole ceiling month, so
    counting every unexcused slot since it would sum two dropped slots a week apart and go
    red until the month ended. Misses count IN A ROW: an excused slot resets them."""
    _channel_row(live, "old-ok", "state", rs.OK, "18 OK replies", "2026-09-04T13:30:00+00:00")
    for day in range(5, 25):
        if day in (10, 20):                    # GitHub never fired these two slots
            continue
        _channel_row(live, f"ceiling-{day}", "state", rs.DEFERRED, CEILING,
                     f"2026-09-{day:02d}T13:30:00+00:00")
    live.commit()
    for day in (11, 21, 24):
        now = datetime(2026, 9, day, 19, 0, tzinfo=UTC)
        assert cv.receipt_findings(live, now.isoformat(), cv.STATE_SLOT, now) == [], day


def test_a_deferral_excuses_the_slot_whose_day_it_lands_in(live):
    """A slot's window is its whole day, 06:17Z to the next 06:17Z: a ceiling run landing
    late (here 12h43m, past the 12h far edge) still excuses its own slot."""
    s21 = datetime(2026, 9, 21, 6, 17, tzinfo=UTC)
    _channel_row(live, "before", "state", rs.DEFERRED, CEILING, "2026-09-21T06:16:59+00:00")
    live.commit()
    assert not cv.state_slot_excused(live, s21)                     # the 09-20 slot's
    _channel_row(live, "late", "state", rs.DEFERRED, CEILING, "2026-09-21T19:00:00+00:00")
    live.commit()
    assert cv.state_slot_excused(live, s21)
    assert not cv.state_slot_excused(live, s21 + timedelta(days=1))
    _channel_row(live, "next", "state", rs.DEFERRED, CEILING, "2026-09-22T06:17:00+00:00")
    live.commit()
    assert cv.state_slot_excused(live, s21 + timedelta(days=1))


@pytest.mark.parametrize("loud", sorted(rs.LOUD))
def test_a_loud_runs_deferral_excuses_nothing(live, loud):
    """A share or mid-run ceiling deferral after a FAILED national call writes `deferred`
    with no `ok`, and NO OK REPLIES beside it (tests/test_unit99_state.py drives that run).
    That slot is a miss, not a planned deferral."""
    s21 = datetime(2026, 9, 21, 6, 17, tzinfo=UTC)
    _channel_row(live, "failed-national", "state", rs.DEFERRED,
                 "monthly ceiling reached (used 7998 of 8000) before master lists",
                 "2026-09-21T13:00:00+00:00")
    _channel_row(live, "failed-national", "state", loud, "evidence",
                 "2026-09-21T13:00:00+00:00")
    live.commit()
    assert not cv.state_slot_excused(live, s21)
    _channel_row(live, "a-quiet-run", "state", rs.DEFERRED, CEILING,
                 "2026-09-21T14:00:00+00:00")
    live.commit()
    assert cv.state_slot_excused(live, s21)


# --- body() and main() ------------------------------------------------------------------


def test_body_renders_channel_class_and_evidence_and_escapes_pipes():
    text = cv.body([("legislation", "credential failure", '"API_KEY_INVALID" a|b'),
                    ("state", "unrecorded", "no row")],
                   "123", "", "https://example.invalid/runs/123")
    lines = text.splitlines()
    # The mention first, as the audit and dom-checks lanes open theirs.
    assert lines[0] == "cc @CSU-J3"
    assert lines[2] == "**collect red** -- run [123](https://example.invalid/runs/123), slot `dispatch`"
    assert "| channel | class | evidence |" in lines
    assert '| legislation | credential failure | "API_KEY_INVALID" a\\|b |' in lines
    assert "| state | unrecorded | no row |" in lines


@pytest.fixture
def main_env(tmp_path, monkeypatch):
    """main() with config.load_env and db.connect replaced, so no `.env` is read and no
    remote is reachable; the environment is the one collect.yml's Verdict step sets."""
    path = str(tmp_path / "t.db")
    db.init_db(path, schema=SCHEMA)
    real_connect = db.connect
    monkeypatch.setattr(cv.config, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(cv.db, "connect", lambda p=None: real_connect(path))
    runner_temp = tmp_path / "runner_temp"
    runner_temp.mkdir()
    started = datetime.now(UTC) - timedelta(minutes=5)
    for k, v in {"GITHUB_RUN_ID": RID, "SLOT": "17 0 * * *",
                 "RUN_STARTED_AT": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "JOB_STATUS": "success", "RUNNER_TEMP": str(runner_temp),
                 "RUN_URL": "https://example.invalid/runs/1"}.items():
        monkeypatch.setenv(k, v)
    conn = real_connect(path)
    now = common.now_iso()
    _channel_row(conn, RID, "legislation", rs.OK, "6 OK replies", now)
    _channel_row(conn, RID, "litigation", rs.OK, "40 OK replies", now)
    _bill(conn, now)
    _case(conn, "72347022", "pending", now)
    conn.commit()
    yield conn, runner_temp / "collect-verdict.md"
    conn.close()


def test_main_exits_0_on_a_clean_run_and_writes_no_body(main_env, capsys):
    _, out = main_env
    assert cv.main() == 0
    assert not out.exists()
    assert "collect verdict: clean" in capsys.readouterr().out


def test_main_exits_1_and_writes_the_body_to_runner_temp_when_red(main_env, capsys):
    conn, out = main_env
    _channel_row(conn, RID, "legislation", rs.CREDENTIAL, "API_KEY_INVALID (HTTP 403)")
    conn.commit()
    assert cv.main() == 1
    raw = out.read_bytes()
    assert b"\r\n" not in raw
    text = raw.decode("utf-8")
    assert "| legislation | credential failure | API_KEY_INVALID (HTTP 403) |" in text
    assert "collect verdict: RED" in capsys.readouterr().out


LOST_COMMIT = ("data commit not pushed: the push was rejected 3 time(s); last repair: rebased "
               "onto a commit that touched nothing under data/; git said: ! [rejected] main -> "
               "main (fetch first)")


def test_the_verdict_names_a_lost_data_commit_on_an_otherwise_clean_run(live, tmp_path):
    """The commit step exits 0 when it gives up, so the job status reads `success`; the
    marker alone is what turns the run red (Corey, 2026-09-30)."""
    _fresh(live, with_state=True)
    assert cv.verdict(live, RID, cv.STATE_SLOT, STARTED, "success", NOW,
                      runner_temp=str(tmp_path)) == []
    (tmp_path / cv.DATA_COMMIT_MARKER).write_text(LOST_COMMIT + "\n", encoding="utf-8")
    assert cv.verdict(live, RID, cv.STATE_SLOT, STARTED, "success", NOW,
                      runner_temp=str(tmp_path)) == [("data", "commit", LOST_COMMIT)]


def test_main_is_red_on_a_lost_data_commit_with_the_database_up(main_env, capsys):
    """main() hands verdict() the step's RUNNER_TEMP: read anywhere else, the marker is
    missed and a run that lost its commit goes green with no comment."""
    _, out = main_env
    (out.parent / cv.DATA_COMMIT_MARKER).write_text(LOST_COMMIT + "\n", encoding="utf-8")
    assert cv.main() == 1
    assert f"| data | commit | {LOST_COMMIT} |" in out.read_text(encoding="utf-8")
    assert "collect verdict: RED" in capsys.readouterr().out


def test_main_still_writes_a_body_and_exits_1_when_the_database_will_not_open(
        main_env, monkeypatch, capsys):
    """The run the empty-URL guard stopped still gets its comment. Only the exception's
    type reaches the body, never its text."""
    _, out = main_env

    def refuse(p=None):
        raise RuntimeError(f"TURSO_DATABASE_URL is empty or unset near {TOKEN}")

    monkeypatch.setattr(cv.db, "connect", refuse)
    assert cv.main() == 1
    text = out.read_text(encoding="utf-8")
    assert "| job | job | the verdict could not open the database: RuntimeError |" in text
    assert TOKEN not in text
    capsys.readouterr()


def test_a_database_read_failure_keeps_the_turso_url_and_token_out_of_body_and_log(
        main_env, monkeypatch, capsys):
    """The body goes to an issue, which GitHub does not mask, and a libsql error can name
    the database: the body carries the exception's type only, and the log line is
    scrubbed of the URL, its bare host and the token."""
    _, out = main_env
    url = "libsql://psephos-fixture-db.example.turso.io"
    monkeypatch.setenv("TURSO_DATABASE_URL", url)
    monkeypatch.setenv("TURSO_AUTH_TOKEN", TOKEN)

    def unreadable(*a, **k):
        raise RuntimeError(f"stream error at psephos-fixture-db.example.turso.io "
                           f"({url}) with {TOKEN}")

    monkeypatch.setattr(cv, "verdict", unreadable)
    assert cv.main() == 1
    text = out.read_text(encoding="utf-8")
    assert "| job | job | the verdict could not read the database: RuntimeError |" in text
    logged = capsys.readouterr()
    for leaked in ("psephos-fixture-db", TOKEN):
        assert leaked not in text
        assert leaked not in logged.out + logged.err
    assert "collect verdict: database read failed -- stream error at [redacted]" in logged.err


# --- collect.yml ------------------------------------------------------------------------


def _workflow() -> dict:
    return yaml.safe_load(
        (REPO / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8"))


def test_collect_yml_grants_issues_write_and_refuses_the_local_fallback():
    doc = _workflow()
    assert doc["permissions"].get("issues") == "write"
    assert doc["permissions"].get("contents") == "write"
    assert doc["jobs"]["collect"]["env"][db.REQUIRE_REMOTE_ENV] == "1"


def test_collect_yml_ends_commit_verdict_issue_heartbeat():
    steps = _workflow()["jobs"]["collect"]["steps"]
    assert [s.get("name") for s in steps[-4:]] == [
        "Commit data changes", "Verdict", "Raise or update the standing issue",
        "Write the run heartbeat"]
    commit, verdict, issue, heartbeat = steps[-4:]

    assert "gh issue" not in commit["run"]

    assert verdict.get("if") == "always()"
    assert "python -m tools.collect_verdict" in verdict["run"]
    assert verdict["env"]["JOB_STATUS"] == "${{ job.status }}"
    assert "continue-on-error" not in verdict, "the verdict's exit 1 is what turns the run red"

    # The Verdict's own outcome, not failure(): a cancelled (timed-out) run keeps the job
    # status `cancelled`, where failure() is false and the red would go uncommented.
    assert verdict.get("id") == "verdict"
    assert issue.get("if") == "${{ always() && steps.verdict.outcome == 'failure' }}"
    assert issue["env"]["GH_REPO"] == "${{ github.repository }}"
    assert 'echo "cc @CSU-J3"' in issue["run"]
    assert issue["env"]["TITLE"] == "collect red"
    assert "collect-verdict.md" in issue["run"]
    assert "select(.title ==" in issue["run"], "exact-title reuse, not a fuzzy search"

    assert heartbeat.get("if") == "always()"
    assert "scripts.write_heartbeat" in heartbeat["run"]

    assert [s.get("name") for s in steps if "gh issue" in str(s.get("run", ""))] == [
        "Raise or update the standing issue"]


def test_the_verdict_and_the_state_collector_agree_on_the_state_slot():
    assert cv.STATE_SLOT == state.STATE_SLOT
    doc = _workflow()
    on = doc.get("on", doc.get(True))  # PyYAML reads a bare `on:` key as True
    assert cv.STATE_SLOT in [entry["cron"] for entry in on["schedule"]]


def test_every_distinct_planned_deferral_prints_and_the_row_keeps_them_all(capsys):
    """R6: every planned deferral prints a line. A loud class prints once; a deferral
    prints each distinct message, so a capped refresh is not lost behind a walk deferral
    noted first in the same run (found by unit 99's litigation tests)."""
    sig = rs.RunSignals("litigation")
    sig.note(rs.DEFERRED, "full walk deferred, request budget spent; walks next run")
    sig.note(rs.DEFERRED, "full walk deferred, request budget spent; walks next run")
    sig.note(rs.DEFERRED, "status refresh capped at 40 of 44 due; the rest resume next run")
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "DEFERRED litigation: full walk deferred, request budget spent; walks next run",
        "DEFERRED litigation: status refresh capped at 40 of 44 due; the rest resume next run",
    ]
    (row,) = [r for r in sig.rows() if r["class"] == rs.DEFERRED]
    assert "full walk deferred" in row["evidence"] and "status refresh capped" in row["evidence"]

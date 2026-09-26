"""Suite for tools/coverage_audit.py.

Offline and deterministic: temp SQLite DB, no network, never touches Turso. `main()` is
NOT exercised -- it calls config.load_env()/db.connect(), which route to production
Turso when the env is set. Tests drive the pure helpers plus a conn-parameterized
section-2 scan, so the suite can never read the remote.

Two things here are regression pins rather than ordinary coverage, and they are the
reason this file exists:

  * The DATE STRIP. `held on 10-28-2025` yields the docket-shaped token `28-2025`, and
    both of the parse artifacts this filter removes were reported as coverage gaps
    before it existed. Remove the strip and section 2 grows false entries that read
    exactly like real ones.
  * The UNION seed set. Against the tracker artifact alone the alarm reads 2 rather
    than 0, the two extras being config seeds that are polled every run (handoff 26
    section 3, shipped as a bug once). `test_alarm_artifact_alone_would_false_fire`
    pins that difference so nobody "simplifies" seeded_keys back to one source.

Run:  pytest tests/test_coverage_audit.py
"""
from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

import pytest  # noqa: E402

from tools import coverage_audit as ca  # noqa: E402


class Row(dict):
    """cases rows are sqlite3.Row-like; dict access is all the helpers use."""


def _row(case_id, docket, court, status="terminated", superseded_by=None, caption="X v. Y"):
    return Row(case_id=case_id, docket_number=docket, court=court, status=status,
               superseded_by=superseded_by, caption=caption)


# --- the acknowledged-blocked register --------------------------------------
#
# EVERY MUTATION BELOW RUNS FROM AN ASSERTED-GREEN BASELINE, which is the point of the
# first test and the reason the rest mean anything. A suppression test that never
# establishes the suppressed state is asserting against nothing: it would pass equally
# if the register did not work at all. So the baseline asserts 0 unacknowledged FIRST,
# and each mutation then asserts that one changed thing puts the row back.

from datetime import date, timedelta  # noqa: E402

ACK_DAY = date(2026, 9, 18)
TODAY = date(2026, 9, 20)          # after acknowledged_on, before review_by


def _ack(**over):
    base = dict(case_id="72335259", docket_number="2:26-cv-00156",
                court="Southern District of West Virginia",
                blocked_because="verify() refuses a non-terminated source",
                unblocked_when="source_terminated",
                acknowledged_on=ACK_DAY, review_by=date(2026, 11, 17))
    return {**base, **over}


def _blocked_row(**over):
    # `pending` is the blocked state: the source has NOT terminated, so the pair cannot
    # be asserted and the acknowledgement holds.
    kw = {"status": "pending"}
    kw.update(over)
    return _row("72335259", "2:26-cv-00156", "Southern District of West Virginia", **kw)


def test_baseline_an_acknowledged_row_leaves_the_count_and_still_prints():
    """THE GREEN BASELINE every mutation below is measured against."""
    alarm = [_blocked_row()]
    unack, blocked, lapsed = ca.partition_alarm(alarm, [_ack()], TODAY)
    assert (len(unack), len(blocked), len(lapsed)) == (0, 1, 0)
    # It is out of the COUNT and out of nothing else -- the row is still in hand, with
    # its entry, for section 1 to print. An acknowledgement, not a suppression.
    assert blocked[0][0]["case_id"] == "72335259"
    assert blocked[0][1]["unblocked_when"] == "source_terminated"


def test_mutation_one_a_fired_condition_does_not_suppress():
    """The designed happy path: the source terminates, the pair becomes assertable, and
    the alarm must go back to demanding the work."""
    alarm = [_blocked_row(status="terminated")]
    unack, blocked, lapsed = ca.partition_alarm(alarm, [_ack()], TODAY)
    assert (len(unack), len(blocked), len(lapsed)) == (0, 0, 1)
    assert "condition fired" in lapsed[0][2]
    # And a lapsed row reaches the exit code, which is the whole claim.
    assert ca.partition_alarm(alarm, [_ack()], TODAY)[2]


def test_mutation_two_an_expired_entry_does_not_suppress():
    """review_by passes with the condition unfired. A blocked row that outlives its
    reason RESURFACES rather than being filed away."""
    alarm = [_blocked_row()]
    expired = _ack(review_by=TODAY - timedelta(days=1))
    unack, blocked, lapsed = ca.partition_alarm(alarm, [expired], TODAY)
    assert (len(unack), len(blocked), len(lapsed)) == (0, 0, 1)
    assert "expired" in lapsed[0][2]
    # The boundary: review_by == today is NOT past due, matching assert-gates' `<`.
    assert ca.partition_alarm(alarm, [_ack(review_by=TODAY)], TODAY)[1]


def test_mutation_three_a_corroborator_mismatch_does_not_suppress():
    """THE P0 MUTATION, and the one the review layer's premise would have missed.

    `court`/`docket_number` freeze when a row is un-seeded, so they survive the rewrite
    that fires section 1. What they do not survive is a RE-SEED under a different
    spelling. An entry keyed on the old pair would then stop applying silently, because
    a re-seeded row does not fire anyway -- and if the row is later dropped again the
    alarm returns with no explanation. Matching on case_id and CHECKING the pair makes
    that lapse loud instead.
    """
    moved = _row("72335259", "2:26-cv-156", "Southern District of West Virginia",
                 status="pending")
    unack, blocked, lapsed = ca.partition_alarm([moved], [_ack()], TODAY)
    assert (len(unack), len(blocked), len(lapsed)) == (0, 0, 1)
    assert "the row moved" in lapsed[0][2]
    # Court alone is enough; the pair is checked together, like the seed join itself.
    court_moved = _blocked_row()
    court_moved["court"] = "District of West Virginia"
    assert ca.partition_alarm([court_moved], [_ack()], TODAY)[2]


def test_the_corroborator_check_runs_before_the_condition():
    """Order matters: a moved row whose status also flipped reports that it MOVED, not
    that the condition fired, because the entry may no longer be about this row at all
    and 'condition fired' would assert something about a pair nobody has checked."""
    both = _row("72335259", "2:26-cv-99999", "Southern District of West Virginia",
                status="terminated")
    why = ca.ack_lapse(both, _ack(), TODAY)
    assert "the row moved" in why


def test_an_unacknowledged_row_is_untouched_by_the_register():
    """The register must not reach rows it does not name -- the failure that would make
    it a blanket silencer rather than a per-row ruling."""
    other = _row("99999999", "1:26-cv-00001", "District of Nowhere", status="pending")
    unack, blocked, lapsed = ca.partition_alarm([other], [_ack()], TODAY)
    assert [r["case_id"] for r in unack] == ["99999999"]
    assert (blocked, lapsed) == ([], [])


def test_an_entry_whose_row_stopped_firing_is_reported_not_counted():
    """An entry that outlives its row is the same rot the expiry exists for."""
    assert [a["case_id"] for a in ca.dangling_acks([], [_ack()])] == ["72335259"]
    assert ca.dangling_acks([_blocked_row()], [_ack()]) == []


# --- the loader refuses rather than falling through -------------------------

def _write(tmp_path, body):
    p = tmp_path / "acks.yaml"
    p.write_text(body, encoding="utf-8")
    return p


BASE_ENTRY = """- case_id: "72335259"
  docket_number: "2:26-cv-00156"
  court: "Southern District of West Virginia"
  blocked_because: "x"
  unblocked_when: source_terminated
  acknowledged_on: 2026-09-18
  review_by: 2026-11-17
"""


def test_the_live_register_loads_and_carries_the_one_entry():
    acks = ca.load_acks()
    assert [a["case_id"] for a in acks] == ["72335259"]
    a = acks[0]
    assert a["unblocked_when"] == "source_terminated"
    assert a["successor"] == "74793201"
    assert isinstance(a["review_by"], date)


def test_an_unrecognised_unblocked_when_is_refused_not_treated_as_never_firing(tmp_path):
    """THE assert-gates.mjs:93 HAZARD, DESIGNED OUT. That script's header records that a
    misspelled `recheck_after` would let an expired claim pass. The same slip here would
    be worse: a value outside the vocabulary would make an entry that can NEVER lapse --
    a permanent silencer created by a typo. It is a hard refusal instead."""
    p = _write(tmp_path, BASE_ENTRY.replace("source_terminated", "source_termianted"))
    with pytest.raises(ValueError, match="closed vocabulary"):
        ca.load_acks(p)


def test_an_unknown_field_is_refused(tmp_path):
    p = _write(tmp_path, BASE_ENTRY + "  recheck_after: 2026-11-17\n")
    with pytest.raises(ValueError, match="unknown field"):
        ca.load_acks(p)


def test_a_missing_required_field_is_refused(tmp_path):
    p = _write(tmp_path, BASE_ENTRY.replace('  review_by: 2026-11-17\n', ""))
    with pytest.raises(ValueError, match="missing required field"):
        ca.load_acks(p)


def test_a_quoted_date_is_refused(tmp_path):
    """A string that looks like a date would compare against `today` as a string and
    the expiry would silently stop working."""
    p = _write(tmp_path, BASE_ENTRY.replace("review_by: 2026-11-17",
                                            'review_by: "2026-11-17"'))
    with pytest.raises(ValueError, match="must be a YAML date"):
        ca.load_acks(p)


def test_a_missing_register_is_empty_rather_than_an_error(tmp_path):
    """No register is the ordinary state for a repo that has acknowledged nothing."""
    assert ca.load_acks(tmp_path / "nope.yaml") == []


# --- section 1, the reconciliation alarm ------------------------------------

def test_alarm_silent_when_every_unseeded_row_is_linked():
    rows = [_row("1", "1:25-cv-00371", "District of New Hampshire", superseded_by="9"),
            _row("2", "5:25-cv-00548", "Middle District of Georgia")]
    seeded = {("5:25-cv-00548", "Middle District of Georgia")}
    assert ca.unreconciled(rows, seeded) == []


def test_alarm_fires_on_the_ky_va_nm_state():
    """Unseeded and unlinked: the exact state KY/VA/NM sat in for weeks."""
    rows = [_row("72334676", "3:26-cv-00019", "Eastern District of Kentucky")]
    assert [r["case_id"] for r in ca.unreconciled(rows, set())] == ["72334676"]


def test_alarm_join_is_docket_and_court_together():
    """Same docket number at a different court is a different case."""
    rows = [_row("1", "1:25-cv-00371", "District of New Hampshire")]
    assert ca.unreconciled(rows, {("1:25-cv-00371", "District of Maryland")})


def test_alarm_artifact_alone_would_false_fire():
    """The handoff-26 trap, pinned. A config seed is polled every run; drop it from
    the seed set and the alarm reports it as covered by nothing."""
    config_seed = _row("71499795", "1:25-cv-03501", "D.D.C.", status="terminated")
    tracker_only = {("5:25-cv-00548", "Middle District of Georgia")}
    union = tracker_only | {("1:25-cv-03501", "D.D.C.")}
    assert ca.unreconciled([config_seed], tracker_only)   # artifact alone: false fire
    assert ca.unreconciled([config_seed], union) == []    # union: silent, correct


# --- section 2, unresolvable references -------------------------------------

def _scan(conn, held):
    return ca.unresolvable_refs(conn, held)


@pytest.fixture()
def conn(tmp_path):
    import sqlite3
    c = sqlite3.connect(tmp_path / "t.db")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE case_entries (case_id TEXT, description TEXT)")
    yield c
    c.close()


def test_dates_are_stripped_before_matching(conn):
    """`held on 10-28-2025` must not become the docket reference `28-2025`."""
    conn.execute("INSERT INTO case_entries VALUES (?, ?)",
                 ("71499795", "TRANSCRIPT held on 10-28-2025; Issuance: 10-30-2025."))
    assert _scan(conn, set()) == {}


def test_real_unresolvable_reference_is_reported(conn):
    conn.execute("INSERT INTO case_entries VALUES (?, ?)",
                 ("71499795", "USCA Case Number 26-5243 for 113 Notice of Appeal"))
    refs = _scan(conn, set())
    assert list(refs) == ["26-5243"]
    assert refs["26-5243"][0][0] == "71499795"


def test_district_original_behind_a_held_circuit_row_is_reported(conn):
    """The four-gap shape: a circuit row naming a district docket nobody holds."""
    conn.execute("INSERT INTO case_entries VALUES (?, ?)",
                 ("72356732", "CASE OPENED. notice of appeal filed in 2:25-cv-09149-DOC-ADS"))
    assert list(_scan(conn, set())) == ["2:25-cv-09149"]


def test_held_dockets_are_not_reported(conn):
    conn.execute("INSERT INTO case_entries VALUES (?, ?)",
                 ("1", "Originating case number: 3:26-cv-00042-RCY"))
    assert _scan(conn, {"3:26-cv-00042"}) == {}


def test_entry_number_brackets_never_match(conn):
    """[6] and [32] are docket entry references; the year-dash form excludes them."""
    conn.execute("INSERT INTO case_entries VALUES (?, ?)",
                 ("72347022", "re [6] Motion, [32] Response, [106] Order [Entered: 02/2"))
    assert _scan(conn, set()) == {}


# --- section 3, the cert watch list -----------------------------------------

def test_cert_watch_holds_terminated_circuit_rows_only():
    rows = [_row("72347022", "26-1225", "Sixth Circuit"),
            _row("73674243", "26-5657", "Sixth Circuit", status="pending"),
            _row("71453026", "2:25-cv-01481", "Western District of Pennsylvania")]
    assert [r["case_id"] for r in ca.cert_watch(rows)] == ["72347022"]


def test_cert_watch_excludes_a_linked_circuit_row():
    rows = [_row("72347022", "26-1225", "Sixth Circuit", superseded_by="99")]
    assert ca.cert_watch(rows) == []


# --- section 4, the derived-column alarm ------------------------------------
# Shown to FIRE before its zero is trusted. A zero-expected check proves nothing until
# the pattern is demonstrated to match something -- the standing invariant this repo
# wrote after a grep returned 0 because it was wrong, not because the log was clean.


@pytest.fixture()
def drift_conn(tmp_path):
    import sqlite3
    c = sqlite3.connect(tmp_path / "d.db")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE cases (case_id TEXT, court TEXT, docket_number TEXT,"
              " latest_entry_at TEXT)")
    c.execute("CREATE TABLE case_entries (id INTEGER PRIMARY KEY, case_id TEXT, entry_at TEXT)")
    yield c
    c.close()


def _case(conn, case_id, stored, entries):
    conn.execute("INSERT INTO cases VALUES (?,?,?,?)", (case_id, "D. Test", "1:25-cv-1", stored))
    for e in entries:
        conn.execute("INSERT INTO case_entries (case_id, entry_at) VALUES (?,?)", (case_id, e))


def test_derived_drift_silent_when_the_column_equals_its_derivation(drift_conn):
    _case(drift_conn, "A", "2026-08-06", ["2026-05-15", "2026-08-06"])
    assert ca.derived_drift(drift_conn) == []


def test_derived_drift_fires_on_the_west_virginia_shape(drift_conn):
    """The exact defect: the column behind an entry the table already holds. This is
    the assertion that makes the 0 in production meaningful."""
    _case(drift_conn, "72335259", "2026-05-15", ["2026-05-15", "2026-07-13", "2026-08-06"])
    fired = ca.derived_drift(drift_conn)
    assert len(fired) == 1
    assert fired[0]["case_id"] == "72335259"
    assert fired[0]["stored"] == "2026-05-15"
    assert fired[0]["derived"] == "2026-08-06"


def test_derived_drift_fires_when_a_case_has_no_entries_but_a_stored_value(drift_conn):
    """The LEFT JOIN arm. An INNER JOIN would drop this row and the alarm would read
    clean on a case whose column is invented -- a different defect, silently hidden."""
    _case(drift_conn, "B", "2026-08-06", [])
    fired = ca.derived_drift(drift_conn)
    assert len(fired) == 1 and fired[0]["derived"] is None


def test_derived_drift_silent_on_a_case_with_neither(drift_conn):
    """No entries and no stored value agree at NULL, and must not fire."""
    _case(drift_conn, "C", None, [])
    assert ca.derived_drift(drift_conn) == []


# --------------------------------------------------------------------------- #
# Section 2 classifies the KIND of gap (handoff 85)
#
# The list used to be undifferentiated and was read as one candidate, which cost a
# handoff. The distinction was already written down -- in the module docstring --
# and a docstring is not what a reader of the OUTPUT sees. Information in the wrong
# place is not available.
# --------------------------------------------------------------------------- #
def test_a_district_token_named_by_a_circuit_row_is_a_predecessor():
    """We hold the appeal and not the case under it: seed, then supersede FORWARD.
    This is the CA/OR/AZ shape, three real gaps closed in handoff 85."""
    assert ca.classify_ref("2:25-cv-09149", ["Ninth Circuit"], ["26-1232"]) == "predecessor"


def test_a_circuit_token_named_by_a_district_row_is_a_successor():
    """We hold the original and not what continued it: the CT/NY and 26-5243 shape."""
    assert ca.classify_ref("26-5243", ["D.D.C."], ["1:25-cv-03501"]) == "successor"


def test_the_naming_rows_own_docket_in_another_notation_is_noise():
    """Arizona's local format renders the HELD 2:26-cv-00066 as the token 26-00066.
    Surfaced by seeding that very docket, so it is a live shape and not a
    hypothetical -- and it is noise rather than a gap."""
    assert ca.classify_ref("26-00066", ["District of Arizona"], ["2:26-cv-00066"]) == "self-ref"


def test_self_reference_wins_over_the_shape_test():
    """Checked FIRST on purpose: a self-reference can otherwise look like a
    successor (circuit-form token, district naming row) and send a reader hunting
    for a docket the project already holds."""
    assert ca.classify_ref("26-00066", ["District of Arizona"], ["2:26-cv-00066"]) != "successor"


def test_an_ordinary_cross_reference_is_neither():
    """Most of what remains is a filing naming some OTHER case -- a related case, a
    miscellaneous docket. Not a coverage gap of either actionable shape, and it must
    not be labelled as one."""
    assert ca.classify_ref("8:25-cv-01370", ["Central District of California"],
                           ["2:25-cv-09149"]) == "reference"


# --- section 5, the vocabulary alarm ----------------------------------------
#
# Synthetic rows only. The suite never reads data/doj_cases.json: the cron rewrites
# that file, so a test pinned to it would go red for reasons that are not the test's
# subject, and would report a UW edit as a defect in this code. The live reading --
# 32 rows, 0 unclassified, 0 null court_id on 2026-09-07 -- is a dated measurement and
# lives in docs/status.md, not here.
#
# Every expect-0 alarm in this file is red-proved before it is trusted. An alarm that
# has never been seen fire is an assumption; this suite's own history is the argument
# (see the zero-expected-grep invariant in docs/status.md).


def _seed(court, court_id, state="Somewhere", docket="1:26-cv-00001"):
    return {"state": state, "court": court, "court_id": court_id,
            "docket_number": docket, "caption": "United States v. X"}


def test_vocab_alarm_fires_on_an_unmapped_court_name():
    # The exact defect that hid for seventeen days: UW types a court name that is not
    # a key, COURT_IDS.get returns None, court_id is null, the row never resolves.
    rows = [_seed("Ninth District", None, state="Somewhere", docket="2:26-cv-00002")]
    out = ca.unclassified_courts(rows)
    assert len(out) == 1
    assert out[0]["court"] == "Ninth District"


def test_vocab_alarm_fires_on_a_null_court_id_even_when_the_name_classifies():
    # The second predicate, and it is not the first one twice. The artifact is a
    # committed file that can outlive an edit to the map, so a real name can arrive
    # beside a null id. Checking only the name would miss it.
    assert ca.unclassified_courts([_seed("Ninth Circuit", None)]) != []


def test_vocab_alarm_fires_on_a_stale_id_whose_name_no_longer_classifies():
    # The mirror case: a non-null id beside a name that is not a key -- what removing
    # an alias would leave behind. Checking only the id would miss THIS one, which is
    # why both predicates are evaluated rather than one standing in for the other.
    assert ca.unclassified_courts([_seed("Eighth Districts", "ca8")]) != []


def test_vocab_alarm_is_silent_on_the_two_aliases():
    # 6470a79's aliases are inside COURT_IDS, so UW's spellings classify. If this ever
    # fires, the aliases were dropped and the two rows they cover stop resolving.
    rows = [_seed("Eighth District", "ca8"), _seed("DC Circuit", "cadc")]
    assert ca.unclassified_courts(rows) == []


def test_vocab_alarm_is_silent_on_ordinary_names():
    rows = [_seed("Ninth Circuit", "ca9"), _seed("District of Minnesota", "mnd"),
            _seed("D.C. Circuit", "cadc")]
    assert ca.unclassified_courts(rows) == []


def test_vocab_alarm_is_silent_on_an_empty_artifact():
    # load_tracker_seeds returns [] when the artifact is missing, which is not an
    # error -- the config seeds still run. An empty list must not read as an alarm.
    assert ca.unclassified_courts([]) == []


def test_vocab_alarm_does_not_police_config_seed_spellings():
    # THE SCOPE CORRECTION, pinned. 'D.D.C.' is how config/sources.yaml spells the
    # district court, with a hand-authored court_id; it is not a COURT_IDS key and
    # never needs to be, because collect_case reads court_id straight off the seed.
    # This section takes ARTIFACT rows, so a config spelling can only reach it by
    # someone widening the caller to pass `cases` rows or config seeds -- which is the
    # scope error C0 caught before it shipped, and would have made this alarm born red
    # on two healthy rows.
    assert ca.unclassified_courts([_seed("D.D.C.", "dcd")]) != []


# --- section 6, the bootstrap alarm -----------------------------------------


@pytest.fixture()
def cases_conn(tmp_path):
    import sqlite3
    c = sqlite3.connect(tmp_path / "cases.db")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE cases (case_id TEXT PRIMARY KEY, docket_number TEXT, "
              "court TEXT, status TEXT, entries_synced_at TEXT, superseded_by TEXT)")
    return c


def _boot_case(conn, case_id, synced, superseded, status="terminated"):
    conn.execute("INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?)",
                 (case_id, "1:26-cv-00001", "District of Somewhere", status,
                  synced, superseded))


def test_bootstrap_alarm_fires_on_a_never_polled_unlinked_row(cases_conn):
    _boot_case(cases_conn, "1", synced=None, superseded=None)
    out = ca.unbootstrapped(cases_conn)
    assert [r["case_id"] for r in out] == ["1"]


def test_bootstrap_alarm_is_silent_on_the_pa_nh_md_shape(cases_conn):
    # A terminated district docket continued as a circuit appeal is COMPLETE, not
    # unbootstrapped. Three real rows have held a NULL mark since handoff 13 and
    # always will; without the superseded_by clause this query reads 3 instead of 0,
    # and a check that needs a caveat every time is a check that stops being run.
    _boot_case(cases_conn, "1", synced=None, superseded="99")
    assert ca.unbootstrapped(cases_conn) == []


def test_bootstrap_alarm_is_silent_on_a_polled_row(cases_conn):
    _boot_case(cases_conn, "1", synced="2026-09-01T00:00:00", superseded=None,
          status="pending")
    assert ca.unbootstrapped(cases_conn) == []


def test_bootstrap_alarm_separates_the_two_clauses(cases_conn):
    # All four combinations at once, so a rewrite that drops either clause fails here
    # rather than in production: only the both-NULL row may fire.
    _boot_case(cases_conn, "fires", synced=None, superseded=None)
    _boot_case(cases_conn, "linked", synced=None, superseded="99")
    _boot_case(cases_conn, "polled", synced="2026-09-01T00:00:00", superseded=None)
    _boot_case(cases_conn, "both", synced="2026-09-01T00:00:00", superseded="99")
    assert [r["case_id"] for r in ca.unbootstrapped(cases_conn)] == ["fires"]


# --- section 7, the state-bill status vocabulary -----------------------------
#
# Section 5's pattern: synthetic rows, never the live table. The tripwire for the one
# off-ramp case still unreachable on live data (ruled 2026-09-26): a NON-NULL status
# the page has no word for. NULL is keyed on /state-bills and must stay silent here.


def _sb(state_bill_id, status, state="PA", bill_number="HR1"):
    return {"state_bill_id": state_bill_id, "state": state,
            "bill_number": bill_number, "status": status}


def test_status_alarm_fires_on_an_unmapped_code():
    rows = [_sb("1", "4"), _sb("2", "9", state="TX", bill_number="SB9")]
    out = ca.unmapped_state_statuses(rows)
    assert [(r["state_bill_id"], r["status"]) for r in out] == [("2", "9")]


def test_status_alarm_fires_on_codes_just_off_the_ramp():
    # 0 is what LegiScan uses for "N/A"; the collector stores a 0 as NULL today
    # (collectors/state.py), so a "0" arriving as a string means that mapping moved.
    # 7 is the first code past Failed. Both must fire rather than be absorbed.
    assert len(ca.unmapped_state_statuses([_sb("1", "0"), _sb("2", "7")])) == 2


def test_status_alarm_is_silent_on_null():
    # PA HR632's shape. Keyed on the page; not this section's subject.
    assert ca.unmapped_state_statuses([_sb("2159038", None, bill_number="HR632")]) == []


def test_status_alarm_is_silent_on_every_code_on_the_ramp():
    rows = [_sb(str(i), code) for i, code in enumerate(ca.STATE_BILL_STATUSES)]
    assert ca.unmapped_state_statuses(rows) == []


def test_status_alarm_is_silent_on_an_empty_table():
    assert ca.unmapped_state_statuses([]) == []


def test_status_vocabulary_is_the_pages_ramp():
    # The page's ramp lives in web/lib/statebill.ts, which Python cannot import. Read
    # the literal out of the source so the two cannot drift apart unnoticed.
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "web" / "lib" / "statebill.ts").read_text(
        encoding="utf-8")
    m = re.search(r"STAGE_ORDER: readonly StageCode\[\] = \[([^\]]*)\]", src)
    assert m, "STAGE_ORDER literal not found in web/lib/statebill.ts"
    assert tuple(re.findall(r'"([^"]+)"', m.group(1))) == ca.STATE_BILL_STATUSES

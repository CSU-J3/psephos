"""Suite for the state collector (collectors/state.py).

Deterministic and offline: builds a temp SQLite DB and monkeypatches
common.http_get with canned LegiScan-shaped payloads (getMasterList / getBill
from tests/fixtures), then drives the real election_match / to_item / collect
pipeline on the change-hash pattern. No network; never touches data/psephos.db.

Run:  pytest tests/test_state.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)  # config / db use repo-relative paths

import common  # noqa: E402
import db  # noqa: E402
from collectors import state  # noqa: E402

FIXTURES = Path(REPO) / "tests" / "fixtures"
BASE = "https://api.legiscan.com/"
KEY = "test-key"
# Mirrors config/sources.yaml state.terms / state.exclude_terms (handoff 9: the bare
# voter/voting terms are kept on measured recall; their residual noise is redacted).
TERMS = ["voter", "voting", "voter registration", "voter roll", "proof of citizenship",
         "mail ballot", "absentee", "provisional ballot", "same-day registration",
         "voter id", "redistricting", "voted by mail", "early voting", "primary election",
         "election audit", "poll watcher", "ballot drop", "election official", "canvass",
         "signature verification",
         # handoff 12 Part C: inverted / adjective+token voter constructions
         "registration of voters", "registered voters", "eligible voters", "provided to voters"]
EXCLUDES = ["voter approval", "proxy voting", "cumulative voting"]
GRADE = ("B", "2")


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


MASTERLIST = _load("legiscan_masterlist.json")
GETBILL = _load("legiscan_getbill.json")


@contextmanager
def _patched(masterlist=None, getbill=None, calls=None):
    """Patch common.http_get to dispatch on the LegiScan `op` param. `calls`, if
    given, records (op, id-or-state) tuples so a test can assert getBill was
    skipped for an unchanged bill."""
    masterlist = MASTERLIST if masterlist is None else masterlist
    getbill = GETBILL if getbill is None else getbill

    def fake(url, params=None, headers=None, timeout=common.DEFAULT_TIMEOUT, throttle=0.0):
        op = params["op"]
        if calls is not None:
            calls.append((op, params.get("id") or params.get("state")))
        if op == "getMasterList":
            return masterlist
        if op == "getBill":
            return getbill
        raise AssertionError(f"unexpected op {op}")

    orig = common.http_get
    common.http_get = fake
    try:
        yield
    finally:
        common.http_get = orig


def _env():
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    db.init_db(path)
    conn = db.connect(path)
    state.register_source(conn, BASE, "B", "2")
    conn.commit()
    return conn


def _count(conn, where="1=1", params=()):
    return conn.execute(f"SELECT COUNT(*) AS n FROM items WHERE {where}", params).fetchone()["n"]


def _getbill_ids(calls):
    return [cid for (op, cid) in calls if op == "getBill"]


# --- pure helpers (no DB, no network) ---------------------------------------

def test_to_item():
    bill = {"bill_id": 1700001, "state": "TX", "bill_number": "SB100",
            "url": "https://legiscan.com/TX/bill/SB100/2026"}
    action = {"date": "2026-02-01", "action": "Referred to Committee on State Affairs"}
    row = state.to_item(bill, action, "B", "2")
    assert row["channel"] == "state"
    assert row["source_id"] == "legiscan"
    assert (row["admiralty_source"], row["admiralty_info"]) == ("B", "2")
    assert row["bill_id"] is None and row["case_id"] is None
    assert row["state_bill_id"] == "1700001"       # str of the LegiScan bill_id, the dimension PK
    assert row["title"] == "TX SB100: Referred to Committee on State Affairs"  # state + number prefix
    assert row["summary"] == "Referred to Committee on State Affairs"
    assert row["occurred_at"].startswith("2026-02-01")  # dated by the action, not fetch time
    assert row["source_url"] == "https://legiscan.com/TX/bill/SB100/2026"
    assert row["content_hash"] == common.content_hash(
        "state", 1700001, "2026-02-01", "Referred to Committee on State Affairs")


def test_title_truncation():
    bill = {"bill_id": 1, "state": "TX", "bill_number": "SB1", "url": ""}
    action = {"date": "2026-01-01", "action": "x" * 400}
    assert len(state.to_item(bill, action, "B", "2")["title"]) == 300


def test_election_filter_matches_real_voting_bills():
    # The actual voting-rights fight matches on its phrase term.
    assert state.election_match({"title": "Relating to voter registration list maintenance"}, TERMS)
    assert state.election_match({"title": "Relating to proof of citizenship for voter eligibility"}, TERMS)
    assert state.election_match({"title": "Relating to mail ballot return deadlines"}, TERMS)
    assert state.election_match({"title": "Relating to redistricting of legislative districts"}, TERMS)
    # A phrase can match via the description too.
    assert state.election_match(
        {"title": "An omnibus elections bill", "description": "Provides for same-day registration."}, TERMS)


def test_election_filter_word_boundary():
    # Word-boundary, NOT substring: a term must not match inside a larger word.
    # "election" (were it a term) must not fire on "selection"; "absentee" must not
    # fire on "absenteeism". These pin the regression the substring filter caused.
    assert not state.election_match(
        {"title": "Relating to the selection of the chief appraiser of an appraisal district"}, TERMS)
    assert not state.election_match(
        {"title": "Relating to workplace absenteeism reporting requirements"}, TERMS)


def test_election_filter_drops_loose_and_offtopic():
    # Loose-term guard: a bare ad-valorem tax-rate "election" must NOT match --
    # bare "election" is out of the term list (it was the flood).
    assert not state.election_match(
        {"title": "Relating to the vote required in an election to approve an ad valorem tax rate",
         "description": "Concerns a local ad valorem tax rate election."}, TERMS)
    # Phrase-aware: bare "registration" is not a term; "alien registration" must not match.
    assert not state.election_match(
        {"title": "Relating to alien registration of nonresident business agents",
         "description": "An act relating to registration of nonresident business agents."}, TERMS)


def test_election_filter_recall_broadened_phrasings():
    # Handoff 9 recall fix: phrasings the narrow list missed now match, mostly via
    # the bare voter/voting terms and the added election-admin phrases.
    M = lambda t, d="": state.election_match({"title": t, "description": d}, TERMS)
    assert M("Relating to documentation of proof of identification for voting")   # 'voting'
    assert M("Relating to an application for a ballot to be voted by mail")        # 'voted by mail'
    assert M("Relating to early voting ballots voted by mail")                     # 'early voting'
    assert M("Relating to the date of the primary election runoff")               # 'primary election'
    assert M("Relating to the operation of a signature verification committee")   # 'signature verification'
    assert M("Relating to state oversight following a county election audit")     # 'election audit'
    assert M("Voter Fraud Prevention Act")                                         # bare 'voter'
    assert M("Restoration of Voting Rights")                                       # bare 'voting'


def test_election_filter_exclusion_redacts_noise_keeps_real():
    # exclude_terms are blanked from the haystack before matching: a bill matching
    # ONLY via a noise phrase drops; one also carrying a real term survives.
    M = lambda t, d="": state.election_match({"title": t, "description": d}, TERMS, EXCLUDES)
    # drops -- the excluded phrase was the sole match (all drawn from the live corpus)
    assert not M("Photo enforcement systems; voter approval")
    assert not M("Relating to the calculation of the voter-approval tax rate for certain cities")  # hyphen
    assert not M("Homeowners' associations; cumulative voting; prohibition")
    assert not M("Precinct committeemen; proxy voting")
    assert not M("Relating to the vote required to approve an ad valorem tax rate",
                 "Requires voter approval for the issuance of a school district bond.")
    # keeps -- a real term survives the redaction
    assert M("Voter approval of early voting changes")                    # 'voter approval' out, 'early voting' left
    assert M("Relating to voter approval; and to voter registration deadlines")  # 'voter registration' left


def test_election_filter_flood_shapes_still_dropped():
    # The incidental shapes the 5b-b spike surfaced stay out (excludes applied).
    M = lambda t, d="": state.election_match({"title": t, "description": d}, TERMS, EXCLUDES)
    assert not M("Relating to authorizing an optional county fee on vehicle registration")  # token 'registration'
    assert not M("County sheriff assistance with certain federal immigration functions")    # 'citizenship' context
    assert not M("Relating to the creation of the Montgomery County Municipal Utility District No. 258")  # MUD


def test_election_filter_plural_phrase_recall():
    # Handoff 12: PHRASE terms tolerate a plural on the last word. These are the
    # exact regressions the plural probe surfaced -- singular-only phrasing missed
    # a bill purely on a trailing 's'.
    M = lambda t, d="": state.election_match({"title": t, "description": d}, TERMS)
    assert M("Relating to penalties for intimidation of election officials")   # 'election officials'
    assert M("Relating to the eligibility to vote in certain primary elections")  # 'primary elections'
    assert M("Post-Election Audits by State Auditor")                          # 'election audits'
    # The singular still matches too -- tolerance is additive, not a replacement.
    assert M("Relating to a single election official")                         # 'election official'


def test_election_filter_bare_token_stays_exact():
    # The deliberate half of the decision: bare `voter` is NOT pluralized, so a bill
    # whose ONLY hit is "voters" does not match. Asserted directly because a future
    # broadening would otherwise silently undo it (these are live-corpus noise shapes:
    # a bond referral, a daylight-time referendum, a League of Women Voters resolution).
    M = lambda t, d="": state.election_match({"title": t, "description": d}, TERMS)
    # Each hits ONLY on "voters" (plural); no bare "voter" and no other term present.
    assert not M("Authorizing a statewide referendum allowing voters to indicate a preference")
    assert not M("League of Women Voters of Georgia; recognize")
    assert not M("Board of Education; members shall be elected by voters of the district")
    # But the singular bare token is unchanged -- it still matches.
    assert M("Voter Fraud Prevention Act")                                      # bare 'voter'


def test_exclusion_plural_symmetry():
    # Handoff 12: exclusion phrases are plural-tolerant on the last word, symmetric
    # with the term side. A synthetic "voter approvals" redacts exactly like the
    # singular, so a bill matching ONLY via the plural noise phrase still drops.
    M = lambda t, d="": state.election_match({"title": t, "description": d}, TERMS, EXCLUDES)
    assert not M("Photo enforcement systems; voter approvals")                  # plural, sole match -> drops
    assert not M("Photo enforcement systems; voter approval")                   # singular, same result
    # A real term still survives the plural redaction.
    assert M("Voter approvals of early voting changes")                         # 'early voting' left


def test_election_filter_inverted_voter_constructions():
    # Handoff 12 Part C: four inverted / adjective+token voter phrases, adopted on
    # measured recall (+10 genuine at 100% over the corpus). Pin the POSITIVES and,
    # because `registered voters`/`eligible voters` are the generic watch terms most
    # exposed to a corpus shift, pin the bond/tax/referendum flood negatives too --
    # the new terms must not widen the flood.
    M = lambda t, d="": state.election_match({"title": t, "description": d}, TERMS, EXCLUDES)
    # positives -- genuine bills the singular list missed
    assert M("Relating to the registration of voters at a polling place")      # registration of voters
    assert M("Relating to the citizenship status of registered voters")        # registered voters
    assert M("Ensuring access to the right to vote by all eligible voters")    # eligible voters
    assert M("Information provided to voters concerning proposed amendments")   # provided to voters
    # precision tell: the inverted form does NOT grab the "registering voters" noise bill (TX HB509)
    assert not M("Prevent accessing private property for the purpose of registering voters")
    # bond / tax / referendum flood shapes stay OUT -- this is the collision the finding turns on:
    # "voters at a[n] election" must not be reachable when "registration of voters at a polling
    # place" is (they share surface form; only the phrase context separates them).
    assert not M("Propose for voter approval the issuance of general obligation bonds")  # excl-redacted
    assert not M("A proposition rejected by voters at a bond election")
    assert not M("Board members shall be elected by the qualified voters at an election")
    assert not M("Authorizing a referendum allowing voters to indicate a preference for standard time")


# --- change-hash pipeline (temp DB + faked LegiScan) ------------------------

def test_collect_filters_changes_and_writes():
    conn = _env()
    calls = []
    with _patched(calls=calls):
        results = state.collect(conn, BASE, KEY, ["TX"], TERMS, GRADE, budget=500, throttle=0.0)
    tx = results["TX"]
    assert tx["election_bills"] == 2          # 2 of 3 pass the filter (alien-registration dropped)
    assert tx["changed"] == 2                 # both new (no stored hash)
    assert tx["getbills"] == 2
    # the off-topic bill is never getBill'd; only the two election bills are
    assert sorted(_getbill_ids(calls)) == [1700001, 1700002]
    assert 1700003 not in _getbill_ids(calls)
    # 2 bills x 3 history actions = 6 items
    assert _count(conn, "channel='state'") == 6
    assert tx["new_items"] == 6
    conn.close()


def test_change_hash_gate_skips_unchanged():
    conn = _env()
    # Pre-store bill 1700001's hash so it matches the masterlist -> must NOT getBill.
    state.remember_hash(conn, 1700001, "aaa111")
    conn.commit()
    calls = []
    with _patched(calls=calls):
        results = state.collect(conn, BASE, KEY, ["TX"], TERMS, GRADE, budget=500, throttle=0.0)
    tx = results["TX"]
    assert _getbill_ids(calls) == [1700002]   # only the changed/new bill is fetched
    assert 1700001 not in _getbill_ids(calls)
    assert tx["changed"] == 1
    assert tx["getbills"] == 1
    assert tx["new_items"] == 3               # one bill's history only
    conn.close()


def test_idempotent_across_runs():
    conn = _env()
    with _patched():
        first = state.collect(conn, BASE, KEY, ["TX"], TERMS, GRADE, budget=500, throttle=0.0)
    calls = []
    with _patched(calls=calls):
        second = state.collect(conn, BASE, KEY, ["TX"], TERMS, GRADE, budget=500, throttle=0.0)
    assert first["TX"]["new_items"] == 6
    assert second["TX"]["new_items"] == 0     # nothing moved -> nothing new
    assert _getbill_ids(calls) == []          # change-hash gate blocks every getBill
    assert _count(conn, "channel='state'") == 6
    conn.close()


def test_insert_ignore_same_action_once():
    conn = _env()
    bill = {"bill_id": 1700001, "state": "TX", "bill_number": "SB100", "url": ""}
    action = {"date": "2026-02-01", "action": "Referred to committee"}
    # items.state_bill_id has an FK, and to_item stamps it; seed the dimension row
    # the collect-path tests get for free from upsert_state_bill.
    state.upsert_state_bill(conn, {}, {"bill_id": 1700001, "number": "SB100"}, "TX")
    row = state.to_item(bill, action, "B", "2")
    assert db.insert_ignore(conn, "items", row) is True
    assert db.insert_ignore(conn, "items", dict(row)) is False   # same content_hash -> dropped
    assert _count(conn, "channel='state'") == 1
    conn.close()


def test_getbill_budget_caps_and_resumes():
    conn = _env()
    calls = []
    with _patched(calls=calls):
        results = state.collect(conn, BASE, KEY, ["TX"], TERMS, GRADE, budget=1, throttle=0.0)
    tx = results["TX"]
    assert len(_getbill_ids(calls)) == 1      # budget=1 -> only one getBill this run
    assert tx["changed"] == 2                 # both seen as changed...
    assert tx["getbills"] == 1                # ...but only one fetched
    # the unfetched bill left NO stored hash, so a follow-up run resumes it
    assert conn.execute("SELECT COUNT(*) AS n FROM state_seen").fetchone()["n"] == 1
    conn.close()


def test_bad_state_isolated():
    conn = _env()

    def fake(url, params=None, headers=None, timeout=common.DEFAULT_TIMEOUT, throttle=0.0):
        if params["op"] == "getMasterList" and params["state"] == "ZZ":
            return {"status": "ERROR", "alert": {"message": "Unknown state abbreviation"}}
        if params["op"] == "getMasterList":
            return MASTERLIST
        return GETBILL

    orig = common.http_get
    common.http_get = fake
    try:
        results = state.collect(conn, BASE, KEY, ["ZZ", "TX"], TERMS, GRADE, budget=500, throttle=0.0)
    finally:
        common.http_get = orig
    assert results["ZZ"]["error_msg"] is not None   # bad state recorded, not raised
    assert results["ZZ"]["new_items"] == 0
    assert results["TX"]["new_items"] == 6          # the good state is unaffected
    conn.close()


# --- state_bills dimension --------------------------------------------------

def test_upsert_state_bill_masterlist_only():
    # Masterlist-only input (bill={}): a row with the right PK, state threaded in
    # (the masterlist has no `state` key), bill_number from `number`, and the
    # getBill-only fields (description, session) null until a poll fetches them.
    conn = _env()
    raw = {"bill_id": 1700001, "number": "SB100", "status": 1, "change_hash": "aaa111",
           "title": "Relating to voter registration procedures",
           "url": "https://legiscan.com/TX/bill/SB100/2026",
           "last_action": "Introduced", "last_action_date": "2026-01-20"}
    state.upsert_state_bill(conn, {}, raw, "TX")
    r = conn.execute("SELECT * FROM state_bills WHERE state_bill_id='1700001'").fetchone()
    assert r["state_bill_id"] == "1700001"         # str(bill_id) PK
    assert r["state"] == "TX"                       # threaded in, not from the payload
    assert r["bill_number"] == "SB100"              # from masterlist `number`
    assert r["title"] == "Relating to voter registration procedures"
    assert r["status"] == "1"                       # numeric code as text
    assert r["description"] is None                 # getBill-only, still unfetched
    assert r["session"] is None                     # getBill-only
    assert r["is_vehicle"] == 0                      # default; 5b-b does not set it
    assert r["last_action_at"].startswith("2026-01-20")
    conn.close()


def test_upsert_state_bill_getbill_enriches():
    # A later getBill payload fills description/session and keeps the same PK.
    conn = _env()
    raw = {"bill_id": 1700001, "number": "SB100", "change_hash": "aaa111"}
    state.upsert_state_bill(conn, {}, raw, "TX")     # masterlist first: desc/session null
    bill = {"bill_id": 1700001, "state": "TX", "bill_number": "SB100",
            "title": "Relating to voter registration procedures",
            "description": "An act relating to voter registration list maintenance.",
            "session": {"session_name": "2026 Regular Session"},
            "status": 1, "url": "https://legiscan.com/x"}
    state.upsert_state_bill(conn, bill, raw, "TX")   # getBill enriches in place
    rows = conn.execute("SELECT * FROM state_bills").fetchall()
    assert len(rows) == 1                            # upsert on the PK, not a second row
    r = rows[0]
    assert r["description"] == "An act relating to voter registration list maintenance."
    assert r["session"] == "2026 Regular Session"
    assert r["title"] == "Relating to voter registration procedures"
    conn.close()


if __name__ == "__main__":
    test_to_item()
    test_title_truncation()
    test_election_filter_matches_real_voting_bills()
    test_election_filter_word_boundary()
    test_election_filter_drops_loose_and_offtopic()
    test_election_filter_recall_broadened_phrasings()
    test_election_filter_exclusion_redacts_noise_keeps_real()
    test_election_filter_flood_shapes_still_dropped()
    test_election_filter_plural_phrase_recall()
    test_election_filter_bare_token_stays_exact()
    test_exclusion_plural_symmetry()
    test_election_filter_inverted_voter_constructions()
    test_collect_filters_changes_and_writes()
    test_change_hash_gate_skips_unchanged()
    test_idempotent_across_runs()
    test_insert_ignore_same_action_once()
    test_getbill_budget_caps_and_resumes()
    test_bad_state_isolated()
    test_upsert_state_bill_masterlist_only()
    test_upsert_state_bill_getbill_enriches()
    print("ok")


# --- the batch boundary (handoff 81) ----------------------------------------
#
# collect() used to commit nothing: main() committed once after it returned, so
# all nine states rode in ONE transaction and a stream failure at the unguarded
# write path discarded every state processed that run. The two existing handlers
# do not catch it -- they wrap getMasterList and getBill, pure HTTP, which is why
# the 2026-08-15 incident (nine states failing at exactly those calls) survived
# while a failure four lines further down would not have.

def _masterlist_for(offset: int):
    """A per-state copy of the masterlist fixture with distinct bill_ids.

    Necessary, not decorative: the fixture is one payload and the change-hash gate
    is keyed on bill_id, so replaying it verbatim for a second state would gate
    every bill out as already-seen and the test would 'pass' having written
    nothing. Each state gets its own bills."""
    ml = json.loads(json.dumps(MASTERLIST))
    for k, v in ml["masterlist"].items():
        if k == "session" or not isinstance(v, dict):
            continue
        v["bill_id"] = v["bill_id"] + offset
        v["change_hash"] = f"{offset}-{v['change_hash']}"
    return ml


OFFSETS = {"TX": 0, "GA": 100, "FL": 200}


@contextmanager
def _patched_states(getbill_fail: str | None = None):
    """Fake LegiScan for several states at once, each with its own bills."""
    def fake(url, params=None, headers=None, timeout=common.DEFAULT_TIMEOUT, throttle=0.0):
        if params["op"] == "getMasterList":
            return _masterlist_for(OFFSETS[params["state"]])
        # Bill ids are 1700001 + the state's offset, so the range test has to be
        # against the id, not against the offset itself.
        if getbill_fail is not None and \
                1700001 + OFFSETS[getbill_fail] <= params["id"] < 1700001 + OFFSETS[getbill_fail] + 100:
            raise RuntimeError("getBill exploded")
        return GETBILL

    orig = common.http_get
    common.http_get = fake
    try:
        yield
    finally:
        common.http_get = orig


class _CountingConn:
    """Delegating proxy that counts commits, so 'per state, not per run' is
    assertable rather than inferred. __getattr__ delegation matters for db.recover,
    which probes `getattr(conn, "reset", None)` and must find nothing here so it
    takes the local rollback path."""

    def __init__(self, raw):
        self._raw = raw
        self.commits = 0

    def commit(self):
        self.commits += 1
        return self._raw.commit()

    def __getattr__(self, name):
        return getattr(self._raw, name)


def _items_for(conn, offset):
    lo, hi = 1700001 + offset, 1700001 + offset + 99
    return conn.execute(
        "SELECT COUNT(*) AS n FROM items WHERE CAST(state_bill_id AS INTEGER) BETWEEN ? AND ?",
        (lo, hi)).fetchone()["n"]


def test_a_failing_state_does_not_discard_the_states_around_it(monkeypatch):
    """THE UNIT. A write-path failure in the middle state costs that state only.

    Durability is checked AFTER an explicit rollback: uncommitted writes are
    visible on the same connection, so counting without one would pass whether or
    not anything was committed -- the check has to be able to fail."""
    raw = _env()
    conn = _CountingConn(raw)

    real = state.upsert_state_bill

    def boom(c, bill, rawbill, st):
        if st == "GA":
            raise RuntimeError("Hrana: stream not found")
        return real(c, bill, rawbill, st)

    monkeypatch.setattr(state, "upsert_state_bill", boom)
    with _patched_states():
        results = state.collect(conn, BASE, KEY, ["TX", "GA", "FL"], TERMS, GRADE,
                                budget=500, throttle=0.0)      # must NOT raise

    conn.rollback()                       # discard anything still pending
    assert _items_for(conn, OFFSETS["TX"]) == 6      # committed before GA ran
    assert _items_for(conn, OFFSETS["GA"]) == 0      # discarded whole
    assert _items_for(conn, OFFSETS["FL"]) == 6      # still attempted after
    assert results["GA"]["error_msg"] is not None
    assert results["GA"]["new_items"] == 0           # not claimed, since nothing persisted
    assert results["TX"]["new_items"] == 6 and results["FL"]["new_items"] == 6
    raw.close()


def test_the_boundary_is_per_state_not_per_run():
    """One commit per state processed. Per bill would be 484 round trips for a
    granularity the change-hash gate does not need."""
    raw = _env()
    conn = _CountingConn(raw)
    with _patched_states():
        state.collect(conn, BASE, KEY, ["TX", "GA", "FL"], TERMS, GRADE,
                      budget=500, throttle=0.0)
    assert conn.commits == 3
    raw.close()


def test_recover_fires_on_the_db_path_and_on_neither_http_path(monkeypatch):
    """The exclusion, pinned as behaviour rather than left as prose. db.recover
    belongs where `conn` IS the failure. The two HTTP handlers wrap getMasterList
    and getBill, where the connection is fine and a reset() would discard the
    state's pending writes for a failure that had nothing to do with it."""
    calls = []
    monkeypatch.setattr(db, "recover", lambda c: calls.append("recover"))

    # (a) a write-path failure -> recover
    raw = _env()
    real = state.upsert_state_bill
    monkeypatch.setattr(state, "upsert_state_bill",
                        lambda c, b, r, st: (_ for _ in ()).throw(RuntimeError("dead stream"))
                        if st == "GA" else real(c, b, r, st))
    with _patched_states():
        state.collect(raw, BASE, KEY, ["GA"], TERMS, GRADE, budget=500, throttle=0.0)
    assert calls == ["recover"]
    raw.close()

    # (b) a getBill failure -> per-bill skip, no recover
    calls.clear()
    monkeypatch.setattr(state, "upsert_state_bill", real)
    raw = _env()
    with _patched_states(getbill_fail="GA"):
        r = state.collect(raw, BASE, KEY, ["GA"], TERMS, GRADE, budget=500, throttle=0.0)
    assert calls == [] and r["GA"]["errors"] == 2
    raw.close()

    # (c) a getMasterList failure -> per-state skip, no recover
    calls.clear()
    raw = _env()

    def fake(url, params=None, headers=None, timeout=common.DEFAULT_TIMEOUT, throttle=0.0):
        return {"status": "ERROR", "alert": {"message": "Unknown state abbreviation"}}

    orig = common.http_get
    common.http_get = fake
    try:
        r = state.collect(raw, BASE, KEY, ["ZZ"], TERMS, GRADE, budget=500, throttle=0.0)
    finally:
        common.http_get = orig
    assert calls == [] and r["ZZ"]["error_msg"] is not None
    raw.close()


def test_a_discarded_state_resumes_on_the_next_run(monkeypatch):
    """The self-healing claim, demonstrated rather than asserted. A discarded
    state stored no change_hash, so the gate re-fetches its bills next run and the
    items land -- which is why per-state partials are the intended failure mode
    and not data loss."""
    raw = _env()
    real = state.upsert_state_bill
    monkeypatch.setattr(state, "upsert_state_bill",
                        lambda c, b, r, st: (_ for _ in ()).throw(RuntimeError("dead stream")))
    with _patched_states():
        state.collect(raw, BASE, KEY, ["GA"], TERMS, GRADE, budget=500, throttle=0.0)
    raw.rollback()
    assert _items_for(raw, OFFSETS["GA"]) == 0
    assert state.seen_hash(raw, 1700001 + OFFSETS["GA"]) is None    # nothing stored

    monkeypatch.setattr(state, "upsert_state_bill", real)           # the blip passes
    with _patched_states():
        r = state.collect(raw, BASE, KEY, ["GA"], TERMS, GRADE, budget=500, throttle=0.0)
    raw.rollback()
    assert r["GA"]["new_items"] == 6
    assert _items_for(raw, OFFSETS["GA"]) == 6
    raw.close()

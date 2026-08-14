"""Suite for the state backfill (scripts/backfill_case_state.py).

Offline and deterministic: temp SQLite DB, a synthetic artifact dict, no network,
never touches Turso. main() is NOT exercised -- it calls config.load_env()/db.connect(),
which route to production Turso when the env is set. Tests drive the conn-parameterized
run()/resolve()/verify()/apply_states() against a temp DB, so the suite cannot write to
the remote.

The refusal cases matter more than the happy path. This script's failure mode is not a
crash, it is a per-state view quietly rendering one fewer jurisdiction than exists, so
every way a row can fail to resolve has to stop the run rather than write a NULL.

Run:  pytest tests/test_case_state.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

import db  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "backfill_case_state", os.path.join(REPO, "scripts", "backfill_case_state.py"))
backfill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill)

# A miniature of the real shape: a plain seeded state, a two-docket state carrying the
# tracker's disambiguation suffix, and a circuit successor whose district predecessor
# has dropped out of the artifact.
ARTIFACT = {
    ("0:25-cv-01", "District of Minnesota"): {"state": "Minnesota"},
    ("5:25-cv-02", "Middle District of Georgia"): {"state": "Georgia (1)"},
    ("1:26-cv-03", "Northern District of Georgia"): {"state": "Georgia (2)"},
    ("26-2684", "Third Circuit"): {"state": "Pennsylvania"},
}
CONFIG_KEYS = {("1:26-cv-99", "D.D.C.")}


def _conn():
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    db.init_db(path)
    return db.connect(path)


def _case(conn, case_id, docket, court, status="pending", superseded_by=None, state=None):
    conn.execute(
        "INSERT INTO cases (case_id, caption, docket_number, court, status, superseded_by, state)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (case_id, f"case {case_id}", docket, court, status, superseded_by, state),
    )
    conn.commit()


def _populated():
    """The four shapes the real table has, in one temp DB."""
    conn = _conn()
    _case(conn, "700", "0:25-cv-01", "District of Minnesota")                  # plain artifact row
    _case(conn, "900", "26-2684", "Third Circuit")                             # circuit successor
    _case(conn, "100", "2:25-cv-01481", "Western District of Pennsylvania",    # unpolled predecessor
          status="terminated", superseded_by="900")
    _case(conn, "800", "1:26-cv-99", "D.D.C.")                                 # config seed, no state
    return conn


def _states(conn):
    return {r["case_id"]: r["state"]
            for r in conn.execute("SELECT case_id, state FROM cases").fetchall()}


def test_artifact_pass_normalizes_and_chain_pass_reaches_the_predecessor():
    """The whole job in one assertion: 700 straight off the artifact, 100 by inheriting
    from the successor it points at, 800 left NULL. The Georgia rows are not in this DB
    -- the suffix itself is pinned in test_litigation -- but 900/100 is the pair that
    only the chain pass can reach, and it is the reason the script exists."""
    conn = _populated()
    records, errs, filled = backfill.run(conn, ARTIFACT, CONFIG_KEYS, apply=True)
    conn.commit()
    assert errs == []
    assert filled == 3
    assert _states(conn) == {"700": "Minnesota", "900": "Pennsylvania",
                             "100": "Pennsylvania", "800": None}
    sources = {r["case_id"]: r["source"] for r in records}
    assert sources["700"] == "artifact"
    assert sources["100"] == "chain <- 900"
    assert sources["800"] == "unresolved"
    conn.close()


def test_dry_run_writes_nothing():
    """Default path. The table is unchanged and the records still describe the work."""
    conn = _populated()
    records, errs, filled = backfill.run(conn, ARTIFACT, CONFIG_KEYS, apply=False)
    assert errs == []
    assert filled == 0
    assert _states(conn) == {"700": None, "900": None, "100": None, "800": None}
    assert any(r["proposed"] == "Pennsylvania" for r in records)
    conn.close()


def test_apply_is_idempotent():
    """Re-running after --apply must pass its own guards and change nothing. The stored
    value now equals the proposal, which is the arm of verify() that would refuse on a
    disagreement -- so this also proves that arm does not fire on agreement."""
    conn = _populated()
    backfill.run(conn, ARTIFACT, CONFIG_KEYS, apply=True)
    conn.commit()
    before = _states(conn)
    records, errs, filled = backfill.run(conn, ARTIFACT, CONFIG_KEYS, apply=True)
    conn.commit()
    assert errs == []
    assert filled == 3
    assert _states(conn) == before
    assert all(r["current"] == r["proposed"]
               for r in records if r["source"] != "unresolved")
    conn.close()


def test_refuses_an_orphan_that_is_not_a_config_seed():
    """A row matching no artifact key, carrying no successor, and absent from the config
    seeds is the failure this script must not paper over: a per-state view would render
    one fewer jurisdiction and nothing would say so. Refusal-first -- the whole run
    writes nothing, including the rows that did resolve."""
    conn = _populated()
    _case(conn, "600", "9:26-cv-77", "District of Nowhere")
    records, errs, filled = backfill.run(conn, ARTIFACT, CONFIG_KEYS, apply=True)
    conn.commit()
    assert filled == 0
    assert len(errs) == 1 and "600" in errs[0]
    assert _states(conn) == {"700": None, "900": None, "100": None, "800": None, "600": None}
    conn.close()


def test_refuses_a_broken_chain():
    """A terminated predecessor whose successor is itself unresolved. Distinct from the
    orphan above: this row HAS a superseded_by, so a reader would expect it covered, and
    the hole would be one the chain pass was supposed to fill."""
    conn = _conn()
    _case(conn, "901", "26-9999", "Ninth Circuit")                     # not in the artifact
    _case(conn, "101", "3:25-cv-05", "District of Oregon",
          status="terminated", superseded_by="901")
    _, errs, filled = backfill.run(conn, ARTIFACT, CONFIG_KEYS, apply=True)
    assert filled == 0
    assert len(errs) == 2 and all(any(cid in e for e in errs) for cid in ("901", "101"))
    conn.close()


def test_refuses_when_the_artifact_state_is_empty():
    """Matched but valueless. This is the one case where "resolved" and "has a value"
    come apart, and writing the NULL would look identical to a config seed."""
    conn = _conn()
    _case(conn, "702", "0:25-cv-07", "District of Iowa")
    artifact = dict(ARTIFACT)
    artifact[("0:25-cv-07", "District of Iowa")] = {"state": "  "}
    _, errs, filled = backfill.run(conn, artifact, CONFIG_KEYS, apply=True)
    assert filled == 0
    assert len(errs) == 1 and "702" in errs[0] and "empty" in errs[0]
    conn.close()


def test_refuses_to_overwrite_a_disagreeing_stored_value():
    """The tracker renaming a state should stop the run and be looked at, not silently
    rewrite 40 rows. Agreement is covered by the idempotence test above."""
    conn = _conn()
    _case(conn, "700", "0:25-cv-01", "District of Minnesota", state="Minnesotta")
    _, errs, filled = backfill.run(conn, ARTIFACT, CONFIG_KEYS, apply=True)
    assert filled == 0
    assert len(errs) == 1 and "Minnesotta" in errs[0]
    assert _states(conn) == {"700": "Minnesotta"}
    conn.close()


def test_config_seed_keys_come_from_sources_yaml_not_a_literal():
    """The guard's allow-list is rebuilt from config, so a third config seed is absorbed
    without editing the script while a genuine orphan still refuses. Reads the real
    file -- no network, and it is the same call litigation.main() makes."""
    keys = backfill.config_seed_keys()
    assert ("1:26-cv-01352", "D.D.C.") in keys      # Common Cause v. DOJ
    assert ("1:25-cv-03501", "D.D.C.") in keys      # LWV v. DHS
    assert all(isinstance(k, tuple) and len(k) == 2 for k in keys)


def test_load_artifact_keys_the_real_file_the_way_the_collector_does():
    """(docket_number, court) against the shipped artifact. Exact by construction --
    upsert_case writes `court` straight off the seed -- and this is the same join key
    tools/coverage_audit uses, so a drift in one shows up in the other."""
    artifact = backfill.load_artifact()
    assert ("5:25-cv-00548", "Middle District of Georgia") in artifact
    assert artifact[("5:25-cv-00548", "Middle District of Georgia")]["state"] == "Georgia (1)"
    assert ("1:26-cv-00485", "Northern District of Georgia") in artifact

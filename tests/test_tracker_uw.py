"""Offline tests for the UW tracker scraper (handoff 4a).

Parse a trimmed fixture -- no network, no DB. Guards: correct docket/court/court_id
extraction, the appealed/circuit row (Wisconsin -> ca7, NO wiwd), the Georgia
double, an unmapped court warning without crashing, and byte-for-byte determinism
across two runs (the empty-diff proof). Run:  pytest tests/test_tracker_uw.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from collectors import tracker_uw as t  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "uw_tracker.html"


def _rows():
    return t.parse_table(FIXTURE.read_text(encoding="utf-8"))


def _by_state(rows, state):
    return next(r for r in rows if r["state"] == state)


def test_row_count_and_sort():
    rows = _rows()
    assert len(rows) == 4
    # sorted by (state, docket_number)
    assert [r["state"] for r in rows] == ["Colorado", "Georgia (1)", "Georgia (2)", "Wisconsin"]


def test_plain_district_row():
    r = _by_state(_rows(), "Colorado")
    assert r["docket_number"] == "1:25-cv-03967"
    assert r["court"] == "District of Colorado"
    assert r["court_id"] == "cod"
    assert r["caption"] == "United States v. Colorado"
    assert r["category"] == "voter-data"


def test_appealed_circuit_row_is_ca7_not_wiwd():
    # The one trap: Wisconsin is appealed, so the current docket is the 7th Circuit,
    # not the district. A wrong/missing court_id would silently skip the case.
    r = _by_state(_rows(), "Wisconsin")
    assert r["court"] == "Seventh Circuit"
    assert r["docket_number"] == "26-2217"
    assert r["court_id"] == "ca7"
    assert r["court_id"] != "wiwd"


def test_georgia_double():
    rows = _rows()
    g1, g2 = _by_state(rows, "Georgia (1)"), _by_state(rows, "Georgia (2)")
    assert (g1["docket_number"], g1["court_id"]) == ("5:25-cv-00548", "gamd")
    assert (g2["docket_number"], g2["court_id"]) == ("1:26-cv-00485", "gand")
    # Provisional caption strips the footnote marker; both resolve to Georgia.
    assert g1["caption"] == g2["caption"] == "United States v. Georgia"


def test_notes_compose_and_link_text():
    # Notes are the B2 framing; anchor text in a cell is captured, NBSP cells dropped.
    g1 = _by_state(_rows(), "Georgia (1)")
    assert g1["notes"].startswith("Claims: Civil Rights Act 1960")
    assert "Key decisions: District court's 1/23/26 venue dismissal." in g1["notes"]


def test_unmapped_court_warns_not_crashes(capsys):
    html = """
    <table><thead><tr>
      <th>State</th><th>Complaint Filed</th><th>Current Federal Court</th>
      <th>Current Case Number</th><th>Current Judge(s)</th><th>Claims</th>
      <th>Status</th><th>Notable Upcoming Hearings</th><th>Key Decisions</th>
    </tr></thead><tbody><tr>
      <td><strong>Testland</strong></td><td>1/1/2026</td><td>District of Nowhere</td>
      <td>1:99-cv-00001</td><td>Doe</td><td>Civil Rights Act 1960</td>
      <td>Pending</td><td>&nbsp;</td><td>&nbsp;</td>
    </tr></tbody></table>
    """
    rows = t.parse_table(html)
    assert len(rows) == 1
    assert rows[0]["court_id"] is None            # emitted, not dropped
    assert "unmapped court" in capsys.readouterr().err


def test_deterministic_serialization(tmp_path):
    rows = _rows()
    out = tmp_path / "doj_cases.json"
    a = t.write_artifact(rows, str(out))
    b = t.write_artifact(t.parse_table(FIXTURE.read_text(encoding="utf-8")), str(out))
    assert a == b                                  # byte-identical across two runs
    assert out.read_text(encoding="utf-8") == a
    assert a.endswith("\n") and "\r" not in a      # LF, no wall-clock timestamp field
    # object keys are sorted (caption before state, etc.)
    assert a.index('"caption"') < a.index('"court"') < a.index('"state"')


def test_every_court_id_is_lowercase_slug():
    # Guards against a stray typo in the verified map (all CL ids are lowercase slugs).
    import re
    for name, cid in t.COURT_IDS.items():
        assert re.fullmatch(r"[a-z0-9]+", cid), f"{name} -> {cid!r} is not a slug"


if __name__ == "__main__":
    for fn in [test_row_count_and_sort, test_plain_district_row,
               test_appealed_circuit_row_is_ca7_not_wiwd, test_georgia_double,
               test_notes_compose_and_link_text, test_every_court_id_is_lowercase_slug]:
        fn()
    print("ok")

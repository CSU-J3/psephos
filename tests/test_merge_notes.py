"""tools/merge_notes.py: every public figure the R1 switch moves, rows against entries,
read from one state of the record (Corey's rulings 5 and d, 2026-09-30)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import common  # noqa: E402
import db  # noqa: E402
from collectors import cl_fold  # noqa: E402
from collectors import litigation as lit  # noqa: E402
from tools import merge_notes as M  # noqa: E402


def test_the_figures_pair_rows_with_entries(tmp_path, monkeypatch):
    dbp = str(tmp_path / "m.db")
    db.init_db(dbp)
    conn = db.connect(dbp)
    conn.execute("INSERT INTO sources (id, name, channel, kind, admiralty_source, admiralty_info)"
                 " VALUES ('courtlistener', 'CL', 'litigation', 'api', 'A', '1')")
    conn.execute("INSERT INTO cases (case_id, caption, status, state) VALUES ('72026664', 'c', 'terminated', 'Nevada')")
    conn.commit()
    e = {"id": 9, "description": "USCA ORDER time schedule", "recap_documents": []}
    monkeypatch.setattr(common, "now_iso", lambda: "2026-08-25T00:00:00+00:00")
    lit.write_entries(conn, "72026664", "c", None, [{**e, "date_filed": "2026-08-24"}], ["order"], [])
    conn.commit()
    monkeypatch.setattr(common, "now_iso", lambda: "2026-08-26T00:00:00+00:00")
    lit.write_entries(conn, "72026664", "c", None, [{**e, "date_filed": "2026-08-20"}], ["order"], [])
    conn.commit()
    cl_fold.refold_case(conn, "72026664")
    conn.execute("UPDATE cases SET latest_entry_at = '2026-08-24T00:00:00'")   # as stored before the repair
    conn.commit()
    f = M.figures(conn, on="2026-10-02")
    assert f["on"] == "2026-10-02" and f["clock"] == "2026-08-26T00:00:00+00:00"
    assert f["wire"]["litigation"]["total"] == [2, 1]
    assert f["map"] == {"entries": [2, 1], "dockets_changed": 1}
    assert f["cases"]["72026664"] == {"entries": [2, 1], "ledger": [2, 1],
                                     "latest_entry_at": ["2026-08-24T00:00:00", "2026-08-20T00:00:00"]}

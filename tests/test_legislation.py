"""Offline test for legislation's per-bill recovery path.

Reproduces the production failure (handoff 15): a bill's write raises, the
per-bill handler runs, and on the remote backend `conn.rollback()` itself raises
a dead-stream ValueError -- so a run that should have skipped one bill instead
crashes. After the fix the handler recovers the connection and reaches the next
bill. No network, no real DB. Run:  pytest tests/test_legislation.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.chdir(REPO)

import config  # noqa: E402
import db  # noqa: E402
from collectors import legislation as leg  # noqa: E402


class _StreamDropRaw:
    """A fake libSQL raw connection whose rollback() raises like a dead Hrana
    stream. commit()/close() succeed. `reopen` hands back a healthy one whose
    rollback() no-ops, standing in for the rebuilt connection."""

    def __init__(self, rollback_raises: bool):
        self.rollback_raises = rollback_raises
        self.commits = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        if self.rollback_raises:
            raise ValueError(
                'Hrana: `api error: `status=404 Not Found, '
                'body={"error":"stream not found: dead:1"}``'
            )

    def close(self):
        pass


def test_bad_bill_recovers_and_run_reaches_next_bill(monkeypatch):
    # Neutralize the real env/schema/network setup in main().
    monkeypatch.setattr(leg.config, "load_env", lambda: None)
    monkeypatch.setattr(leg.db, "init_db", lambda *a, **k: None)
    monkeypatch.setattr(leg.config, "require_env", lambda name: "key")
    monkeypatch.setattr(leg.config, "grade", lambda g: ("Congress.gov", "A1"))
    monkeypatch.setattr(leg, "register_source", lambda *a, **k: None)
    monkeypatch.setattr(
        leg.config,
        "load_sources",
        lambda: {
            "legislation": {
                "api": {"base": "http://example/", "key_env": "K"},
                "default_grade": "A1",
                "watchlist": [{"bill_id": "bad-1"}, {"bill_id": "good-1"}],
            }
        },
    )

    # A remote-shaped connection: the live raw's rollback() raises (dead stream);
    # reopen() returns a healthy raw so reset() heals the connection.
    dead = _StreamDropRaw(rollback_raises=True)
    healthy = _StreamDropRaw(rollback_raises=False)
    conn = db._Conn(dead, reopen=lambda: healthy)
    monkeypatch.setattr(leg.db, "connect", lambda *a, **k: conn)

    seen = []

    def fake_collect_bill(conn, base, key, throttle, entry, *a, **k):
        seen.append(entry["bill_id"])
        if entry["bill_id"] == "bad-1":
            raise ValueError("simulated bad bill (any write failure)")
        return {"bill_id": entry["bill_id"], "new_actions": 0,
                "new_relations": 0, "new_items": 0}

    monkeypatch.setattr(leg, "collect_bill", fake_collect_bill)

    # Current code calls the dead rollback() in the handler and crashes; the fix
    # recovers and the loop reaches the second bill.
    assert leg.main() == 0
    assert seen == ["bad-1", "good-1"]

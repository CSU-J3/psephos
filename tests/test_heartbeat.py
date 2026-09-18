"""The `runs` table, its writer, and the workflow step that invokes it, joined.

WHY THIS EXISTS, in the shape tests/test_snapshot_staging.py exists. Three things have
to agree about one table and they live in three files: `schema.sql` declares the
columns, `scripts/write_heartbeat.py` builds the row, and `.github/workflows/collect.yml`
runs it. A prose comment in any of them cannot fail. The specific silent failure this
guards is the same one the snapshot staging test guards: a column added in one place and
not the other, where nothing errors because the write simply omits it and the read
simply sees NULL.

AND THE STEP'S `if: always()` IS ASSERTED, not just written. It is the whole reason the
step exists as a separate step: the page distinguishes a run that FAILED from a slot
that never fired by whether a row is present, so a heartbeat that is skipped on failure
collapses the two cases this table was built to tell apart. Deleting `if: always()`
would break nothing a collector test can see, and every run would go on being green.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import common  # noqa: E402
import db  # noqa: E402


def _writer():
    spec = importlib.util.spec_from_file_location(
        "write_heartbeat", REPO / "scripts" / "write_heartbeat.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _schema_columns(table: str) -> list[str]:
    text = (REPO / "schema.sql").read_text(encoding="utf-8")
    m = re.search(
        r"CREATE TABLE IF NOT EXISTS " + table + r"\s*\((.*?)\n\);", text, re.S
    )
    assert m, f"{table} is not declared in schema.sql"
    cols = []
    for line in m.group(1).splitlines():
        line = line.split("--")[0].strip()
        if not line or line.startswith(("UNIQUE", "PRIMARY KEY", "FOREIGN KEY")):
            continue
        cols.append(line.split()[0].strip(","))
    return cols


@pytest.fixture
def live():
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    db.init_db(path)
    conn = db.connect(path)
    yield conn
    conn.close()


def test_the_writers_row_is_exactly_the_declared_columns(live):
    """The join the file exists for. A column in one and not the other is silent."""
    wh = _writer()
    row = wh.build_row(live, "1", "17 0 * * *", common.now_iso(), "success")
    assert sorted(row) == sorted(_schema_columns("runs"))


def test_items_written_counts_only_this_run(live):
    """`fetched_at` is write-once, which is what makes the count exact rather than a
    guess -- the same property that makes MAX(fetched_at) useless for staleness."""
    wh = _writer()
    live.execute(
        "INSERT INTO sources (id, name, channel, kind, admiralty_source, admiralty_info) "
        "VALUES ('s','s','news','rss','A','1')"
    )
    start = common.now_iso()
    for stamp, h in [("2026-01-01T00:00:00+00:00", "before"), (common.now_iso(), "during")]:
        live.execute(
            "INSERT INTO items (channel, source_id, source_url, title, fetched_at, "
            "admiralty_source, admiralty_info, content_hash) VALUES (?,?,?,?,?,?,?,?)",
            ("news", "s", "u", "t", stamp, "A", "1", h),
        )
    row = wh.build_row(live, "1", "17 0 * * *", start, "success")
    assert row["items_written"] == 1


def test_a_Z_suffixed_start_counts_the_same_as_an_offset_one(live):
    """THE TRAP THE NORMALIZER EXISTS FOR, asserted rather than described.

    The count is a STRING comparison. `common.now_iso()` renders `+00:00`; GitHub
    renders `Z`; and lexically "Z" (0x5A) sorts above "." (0x2E), so an unnormalized
    `...:32Z` compares GREATER than `...:32.123456+00:00` and silently drops every item
    written in the run's first second.

    BOTH STAMPS ARE LITERALS, AND THAT IS THE FIX RATHER THAN THE STYLE. This test was
    written against `common.now_iso()` twice -- `start`, then the item -- with the Z
    form built by replacing the offset on the first. That construction reproduces the
    trap only when the two calls land in the SAME MICROSECOND, because the Z it builds
    still carries `.123456` and the comparison only reaches the `Z`/`+` position when
    every digit before it matches. Windows' clock granularity is ~15.6ms, so two
    consecutive calls are identical 199 times in 200 and the trap fired on every local
    run; Linux resolves to the microsecond, the stamps differ at the fractional digits,
    and the raw comparison read 1. It failed on ci.yml's runner, green on the author's
    machine, from 2026-09-17 until this commit.

    The literals also reproduce the RIGHT shape. `collect.yml` sets RUN_STARTED_AT from
    `date -u +%Y-%m-%dT%H:%M:%SZ` -- truncated to the second, no fraction at all -- so
    the string the normalizer actually receives is `...:32Z`, never `...:32.123456Z`.
    Against a second-truncated Z the comparison reaches the `Z` on the very next
    character, which is why this now reads 0 on any clock.
    """
    wh = _writer()
    live.execute(
        "INSERT INTO sources (id, name, channel, kind, admiralty_source, admiralty_info) "
        "VALUES ('s','s','news','rss','A','1')"
    )
    # The same instant in the two renderings: GitHub's, then an item stamped inside
    # that run's first second.
    z = "2026-09-18T19:20:32Z"
    live.execute(
        "INSERT INTO items (channel, source_id, source_url, title, fetched_at, "
        "admiralty_source, admiralty_info, content_hash) VALUES (?,?,?,?,?,?,?,?)",
        ("news", "s", "u", "t", "2026-09-18T19:20:32.500000+00:00", "A", "1", "h"),
    )
    raw = live.execute(
        "SELECT COUNT(*) FROM items WHERE fetched_at >= ?", (z,)
    ).fetchone()[0]
    assert raw == 0, "the trap has stopped reproducing; the normalizer's reason is stale"
    assert wh.build_row(live, "1", "s", z, "success")["items_written"] == 1


def test_the_workflow_renders_run_started_at_truncated_to_the_second(live):
    """The literal above is only the right literal while collect.yml renders that shape.

    The test beside this one pins a trap against `...:32Z`. If the workflow ever gained
    a fractional RUN_STARTED_AT the trap would still be real but this would no longer be
    the string producing it, and the test would go on passing against a shape nothing
    sends. Pinning the format string is what keeps the two joined.
    """
    text = (REPO / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8")
    assert "RUN_STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)" in text


def test_a_rerun_replaces_its_row_rather_than_adding_one(live):
    """Upsert on run_id: a GitHub re-run reuses the id, and two rows for one run would
    make the page's per-slot lookup ambiguous."""
    wh = _writer()
    row = wh.build_row(live, "42", "17 0 * * *", common.now_iso(), "failure")
    db.upsert(live, "runs", row, "run_id")
    db.upsert(live, "runs", dict(row, conclusion="success"), "run_id")
    live.commit()
    got = live.execute("SELECT COUNT(*), MAX(conclusion) FROM runs").fetchone()
    assert (got[0], got[1]) == (1, "success")


def test_the_workflow_step_is_unconditional_and_last():
    """`if: always()` is the step's reason to exist. Without it a failed run leaves no
    row and reads, from the page, exactly like a slot that never fired."""
    import yaml

    doc = yaml.safe_load((REPO / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8"))
    steps = doc["jobs"]["collect"]["steps"]
    hb = [s for s in steps if "scripts.write_heartbeat" in str(s.get("run", ""))]
    assert len(hb) == 1, "exactly one step writes the heartbeat"
    assert hb[0].get("if") == "always()", "the heartbeat must survive a failed run"
    assert steps[-1] is hb[0], "the heartbeat is the run's last step"
    assert "RUN_STARTED_AT" in str(steps[0].get("run", "")), (
        "the job's start must be stamped by the first step, before anything can fail"
    )


def test_the_run_status_fixture_is_dev_only():
    """The fixture renders four states the live page cannot show, off fabricated rows.

    It is a real route so it can be LOOKED AT -- the first draft lived under
    `app/_fixture/`, and a leading underscore makes a Next folder private, which excludes
    it from routing entirely and made the fixture 404. So the guard is what keeps it off
    the deployed site, and a guard nothing asserts is a guard someone deletes.
    """
    src = (REPO / "web" / "app" / "fixture" / "run-status" / "page.tsx").read_text(
        encoding="utf-8"
    )
    assert 'process.env.NODE_ENV === "production"' in src
    assert "notFound()" in src


def test_the_heartbeat_is_never_exported():
    """Never exported, by design: the page reads it live. If a snapshot ever carried it,
    tests/test_snapshot_staging would have to reach it and this line is the reminder."""
    text = (REPO / "export" / "snapshots.py").read_text(encoding="utf-8")
    assert "FROM runs" not in text and "runs.json" not in text

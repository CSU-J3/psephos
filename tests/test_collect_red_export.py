"""A red collectors step still exports and commits (Corey, 2026-10-05, ruling A).

One failed channel must not freeze the snapshot or the record's clock
(data/generated_at.json, the newest item fetched). collect.yml's export step runs whenever
the collectors step RAN, succeeded or failed, and never after a cancellation or when an
earlier failure skipped the collectors; the commit follows a successful export. The job
still ends red, so the Verdict names the failed part.

Two halves, both joined to the files they test:
  * the export's and the commit's `if:` conditions, read from collect.yml and evaluated by
    a small reader of GitHub's expression syntax -- the status functions, step outcomes,
    ==, !=, &&, ||, !, parentheses and quoted strings, which is what these steps use;
  * a planted collector failure -- the step's REAL script under bash, with a stub python
    whose litigation raises -- then the export's own code on a temp database where another
    channel wrote an item during the run: the snapshot and data/generated_at.json advance
    to it. Needs a POSIX bash (Actions' ubuntu runner; Git Bash locally); skipped without.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import common  # noqa: E402
import db  # noqa: E402
from export import snapshots  # noqa: E402
from tools import collect_verdict as cv  # noqa: E402

SCHEMA = str(REPO / "schema.sql")
STATUS = ("success()", "failure()", "cancelled()", "always()")
_TOKEN = re.compile(r"(\(|\)|&&|\|\||==|!=|!)|('(?:[^']|'')*')|([A-Za-z_][\w.\-]*\(\))|([A-Za-z_][\w.\-]*)")


def _tokens(expr: str) -> list[str]:
    out, i = [], 0
    while i < len(expr):
        if expr[i].isspace():
            i += 1
            continue
        m = _TOKEN.match(expr, i)
        if not m:
            raise ValueError(f"cannot read {expr[i:]!r}")
        out.append(next(g for g in m.groups() if g is not None))
        i = m.end()
    return out


def evaluate(cond: str | None, before: dict[str, str], cancelled: bool = False) -> bool:
    """Whether a step with this `if:` runs, given the outcomes of the steps before it and
    whether the run was cancelled. GitHub's rules: an expression with no status function
    is `success() && (...)`; success() means no earlier step failed and no cancellation;
    an unrun step's outcome reads ''."""
    expr = (cond or "").strip()
    if expr.startswith("${{") and expr.endswith("}}"):
        expr = expr[3:-2].strip()
    toks = _tokens(expr)
    if not any(t in STATUS for t in toks):
        toks = ["success()"] + (["&&", "("] + toks + [")"] if toks else [])
    failed = any(v == "failure" for v in before.values())
    fn = {"success()": not cancelled and not failed, "failure()": failed,
          "cancelled()": cancelled, "always()": True}
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else None

    def take():
        nonlocal pos
        pos += 1
        return toks[pos - 1]

    def value(t):
        if t in fn:
            return fn[t]
        if t.startswith("'"):
            return t[1:-1].replace("''", "'")
        parts = t.split(".")
        if len(parts) == 3 and parts[0] == "steps" and parts[2] in ("outcome", "conclusion"):
            return before.get(parts[1], "")
        raise ValueError(f"unknown term {t!r}")

    def primary():
        t = take()
        if t == "(":
            v = either()
            assert take() == ")"
            return v
        if t == "!":
            return not primary()
        v = value(t)
        if peek() in ("==", "!="):
            op, rhs = take(), value(take())
            return (str(v).lower() == str(rhs).lower()) == (op == "==")
        return v

    def both():
        v = primary()
        while peek() == "&&":
            take()
            v = bool(primary()) and bool(v)
        return v

    def either():
        v = both()
        while peek() == "||":
            take()
            v = bool(both()) or bool(v)
        return v

    v = either()
    assert pos == len(toks), f"unread: {toks[pos:]}"
    return bool(v)


def _steps() -> list[dict]:
    wf = yaml.safe_load((REPO / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8"))
    return wf["jobs"]["collect"]["steps"]


def _if(name: str) -> str | None:
    return next(s for s in _steps() if s.get("name") == name).get("if")


EXPORT, COMMIT = "Export JSON snapshots", "Commit data changes"
UP_TO_COLLECTORS = {"checkout": "success", "python": "success", "deps": "success"}


def test_the_reader_follows_githubs_status_rules():
    assert evaluate(None, {"a": "success"}) and not evaluate(None, {"a": "failure"})
    assert evaluate("always()", {"a": "failure"}, cancelled=True)
    assert evaluate("${{ !cancelled() }}", {"a": "failure"})
    assert not evaluate("${{ !cancelled() }}", {"a": "success"}, cancelled=True)
    assert evaluate("failure()", {"a": "failure"}) and not evaluate("failure()", {"a": "success"})
    assert evaluate("${{ steps.a.outcome == 'success' }}", {"a": "success"})
    assert not evaluate("${{ steps.a.outcome == 'success' }}", {"a": "success", "b": "failure"})


@pytest.mark.parametrize("collectors, cancelled, runs", [
    ("failure", False, True),       # the ruling: one failed channel still exports
    ("success", False, True),
    ("skipped", False, False),      # an earlier step failed; nothing was collected
    ("cancelled", True, False),     # never after a cancellation...
    ("failure", True, False),       # ...including one that lands after the collectors ended
    ("success", True, False),
])
def test_the_export_runs_whenever_the_collectors_step_ran_and_never_after_a_cancellation(
        collectors, cancelled, runs):
    before = dict(UP_TO_COLLECTORS, collectors=collectors)
    if collectors == "skipped":
        before["deps"] = "failure"
    assert evaluate(_if(EXPORT), before, cancelled) is runs


@pytest.mark.parametrize("collectors, export, cancelled, runs", [
    ("failure", "success", False, True),
    ("success", "success", False, True),
    ("failure", "failure", False, False),     # nothing exported, nothing to commit
    ("skipped", "skipped", False, False),
    ("failure", "cancelled", True, False),
])
def test_the_commit_follows_a_successful_export(collectors, export, cancelled, runs):
    before = dict(UP_TO_COLLECTORS, collectors=collectors, export=export)
    assert evaluate(_if(COMMIT), before, cancelled) is runs


def test_the_verdict_and_the_heartbeat_still_run_on_every_outcome():
    for name in ("Verdict", "Write the run heartbeat"):
        assert evaluate(_if(name), dict(UP_TO_COLLECTORS, collectors="failure"), cancelled=True)


def _bash() -> str | None:
    b = shutil.which("bash")
    if not b or "system32" in b.lower():      # the WSL launcher is not a POSIX bash here
        return None
    return b


STUB = ('#!/usr/bin/env bash\n'
        'case "$2" in\n'
        '  collectors.litigation) exec "$REAL_PYTHON" -c \'raise ValueError("Hrana: connection closed")\' ;;\n'
        '  *) echo "$2: ran" ;;\n'
        'esac\n')


def _item(conn, key: str, fetched_at: str) -> None:
    db.insert_ignore(conn, "items", {
        "channel": "executive", "source_id": "federal-register",
        "source_url": f"https://www.federalregister.gov/d/{key}", "title": f"Fixture rule {key}",
        "occurred_at": fetched_at[:10], "fetched_at": fetched_at,
        "admiralty_source": "A", "admiralty_info": "1",
        "content_hash": common.content_hash("executive", key)})


@pytest.mark.skipif(_bash() is None, reason="no POSIX bash on this machine")
def test_after_a_planted_collector_failure_the_snapshot_and_its_clock_still_advance(tmp_path, monkeypatch):
    # The step, with litigation raising: it runs every part and ends red.
    stubs = tmp_path / "bin"
    stubs.mkdir()
    (stubs / "python").write_bytes(STUB.encode("utf-8"))
    (stubs / "python").chmod(0o755)
    temp = tmp_path / "runner-temp"
    temp.mkdir()
    script = next(s for s in _steps() if s.get("name") == "Run collectors")["run"]
    env = {**os.environ, "RUNNER_TEMP": temp.as_posix(), "REAL_PYTHON": Path(sys.executable).as_posix(),
           "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run([_bash(), "--noprofile", "--norc", "-e", "-c", script],
                       env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 1 and "collectors.executive: ran" in r.stdout, r.stdout + r.stderr
    before = dict(UP_TO_COLLECTORS, collectors="failure")
    assert evaluate(_if(EXPORT), before)

    # The export's own code, on a database where executive wrote an item during that run.
    path = str(tmp_path / "t.db")
    db.init_db(path, schema=SCHEMA)
    conn = db.connect(path)
    conn.execute("INSERT INTO sources (id, name, channel, kind, admiralty_source) "
                 "VALUES ('federal-register', 'Federal Register', 'executive', 'api', 'A')")
    _item(conn, "a", "2026-10-04T12:20:00+00:00")       # the last run's newest item
    conn.commit()
    monkeypatch.chdir(REPO)
    out = {}
    for name in ("BILLS_PATH", "CASES_PATH", "EXECUTIVE_PATH", "STATE_BILLS_PATH", "NEWS_PATH",
                 "GENERATED_AT_PATH"):
        out[name] = tmp_path / Path(getattr(snapshots, name)).name
        monkeypatch.setattr(snapshots, name, str(out[name]))
    real_connect = db.connect                            # snapshots.db is this module
    monkeypatch.setattr(snapshots.config, "load_env", lambda *a, **k: None)
    monkeypatch.setattr(snapshots.db, "connect", lambda *a, **k: real_connect(path))
    assert snapshots.main() == 0
    clock_before = json.loads(out["GENERATED_AT_PATH"].read_text(encoding="utf-8"))["generated_at"]
    executive_before = json.loads(out["EXECUTIVE_PATH"].read_text(encoding="utf-8"))

    _item(conn, "b", "2026-10-05T20:41:00+00:00")       # executive ran while litigation failed
    conn.commit()
    conn.close()
    assert snapshots.main() == 0
    clock_after = json.loads(out["GENERATED_AT_PATH"].read_text(encoding="utf-8"))["generated_at"]
    executive_after = json.loads(out["EXECUTIVE_PATH"].read_text(encoding="utf-8"))
    assert (clock_before, clock_after) == ("2026-10-04T12:20:00+00:00", "2026-10-05T20:41:00+00:00")
    assert len(executive_after) == len(executive_before) + 1

    # The commit follows the export, and the Verdict still names the failed part.
    before["export"] = "success"
    assert evaluate(_if(COMMIT), before)
    outcomes = " ".join(f"{k}={v}" for k, v in {**before, "commit": "success"}.items())
    assert cv.job_findings("failure", outcomes, str(temp)) == [
        ("job", "job", "`Run collectors` failed: litigation exited non-zero")]

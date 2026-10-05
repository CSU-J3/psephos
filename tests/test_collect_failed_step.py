"""collect.yml runs every channel and names each one that failed (Corey, 2026-10-05).

The 2026-10-04 06:17Z slot's run (37201585654) died in the litigation collector on a Turso
drop. `bash -e` ended the collectors step there, so executive, news and state never ran,
and the Verdict's only line for it was "an earlier step ended `failure`"; it went unread
for a day and a half. Every part of the step now runs whatever the one before it did,
keeping its output at $RUNNER_TEMP/channel-<name>.log and its exit as a `<name> <code>`
line of $RUNNER_TEMP/channels. The step fails at its end if any part failed, and the
Verdict names the step and each failed part with its log's last line, scrubbed -- or by
the channel's own `failed` row, which run_signals.guarded writes when it can.

The planted case runs the step's REAL script, taken from collect.yml, under bash, with a
stub `python` first on PATH whose litigation raises that run's own exception, a planted
credential in its message. Needs a POSIX bash (Actions' ubuntu runner; Git Bash locally);
skipped without.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import db  # noqa: E402
import run_signals as rs  # noqa: E402
from tools import collect_verdict as cv  # noqa: E402

PLANTED = "PLANTED-courtlistener-token-0123456789abcdef"
RAISED = "ValueError: Hrana: `http error: `connection closed before message completed``"
# Litigation raises the 2026-10-04 run's exception, the planted credential in its message;
# every other part says it ran and exits 0.
STUB = ('#!/usr/bin/env bash\n'
        'case "$2" in\n'
        '  collectors.litigation)\n'
        '    exec "$REAL_PYTHON" -c \'import os\n'
        'raise ValueError("Hrana: `http error: `connection closed before message completed`` '
        'token=" + os.environ["COURTLISTENER_TOKEN"])\' ;;\n'
        '  *) echo "$2: ran" ;;\n'
        'esac\n')
OUTCOMES = "checkout=success python=success deps=success collectors=failure export=skipped commit=skipped"
# The step's parts in run order: the five channels, and tracker_uw ahead of litigation.
PARTS = ("legislation", "tracker_uw", "litigation", "executive", "news", "state")
RID = "37201585654"
URL = f"https://github.com/CSU-J3/psephos/actions/runs/{RID}"
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
STARTED = "2026-10-04T06:40:00+00:00"
DURING = "2026-10-04T06:50:00+00:00"
JOB_LINE = ("job", "job", "`Run collectors` failed: litigation exited non-zero")


def _bash() -> str | None:
    b = shutil.which("bash")
    if not b or "system32" in b.lower():      # the WSL launcher is not a POSIX bash here
        return None
    return b


needs_bash = pytest.mark.skipif(_bash() is None, reason="no POSIX bash on this machine")


def _steps() -> list:
    wf = yaml.safe_load((REPO / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8"))
    return wf["jobs"]["collect"]["steps"]


def _named(name: str) -> dict:
    return next(s for s in _steps() if s.get("name") == name)


@pytest.fixture
def live(tmp_path, monkeypatch):
    monkeypatch.chdir(REPO)       # the Verdict's rotation check reads config/sources.yaml
    path = str(tmp_path / "t.db")
    db.init_db(path, schema=str(REPO / "schema.sql"))
    conn = db.connect(path)
    yield conn
    conn.close()


def _row(conn, channel, cls, evidence):
    conn.execute("INSERT INTO channel_runs (run_id, channel, class, evidence, written_at) "
                 "VALUES (?,?,?,?,?)", (RID, channel, cls, evidence, DURING))


def _the_others_recorded(conn):
    """Every channel but litigation wrote its row this run, and the receipts are fresh."""
    for ch, ev in (("legislation", "6 OK replies"), ("executive", "10 OK replies"),
                   ("news", "10 OK replies"), ("state", "18 OK replies")):
        _row(conn, ch, rs.OK, ev)
    conn.execute("INSERT INTO bills (bill_id, congress, bill_type, number, updated_at) "
                 "VALUES ('hr22-119', 119, 'hr', 22, ?)", (DURING,))
    conn.execute("INSERT INTO cases (case_id, caption, status, status_checked_at) "
                 "VALUES ('72347022', 'United States v. Fixture', 'pending', ?)", (DURING,))
    conn.commit()


def _record(temp: Path, codes: dict[str, int], logs: dict[str, str]) -> None:
    """The step's record, as it leaves it: one `<name> <code>` line a part, and its log."""
    (temp / "channels").write_text("".join(f"{p} {codes.get(p, 0)}\n" for p in PARTS), encoding="utf-8")
    for part, text in logs.items():
        (temp / f"channel-{part}.log").write_text(text, encoding="utf-8")


@needs_bash
def test_a_planted_litigation_exception_runs_every_other_channel_and_ends_red_naming_it(
        tmp_path, monkeypatch, live):
    stubs = tmp_path / "bin"
    stubs.mkdir()
    (stubs / "python").write_bytes(STUB.encode("utf-8"))
    (stubs / "python").chmod(0o755)
    temp = tmp_path / "runner-temp"
    temp.mkdir()
    env = {**os.environ, "RUNNER_TEMP": temp.as_posix(), "REAL_PYTHON": Path(sys.executable).as_posix(),
           "COURTLISTENER_TOKEN": PLANTED, "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run([_bash(), "--noprofile", "--norc", "-e", "-c", _named("Run collectors")["run"]],
                       env=env, capture_output=True, text=True, timeout=120)
    out = r.stdout

    # The step fails, at its end: every part after litigation still ran, in order.
    assert r.returncode == 1, out + r.stderr
    assert (temp / "channels").read_text(encoding="utf-8").splitlines() == [
        "legislation 0", "tracker_uw 0", "litigation 1", "executive 0", "news 0", "state 0"]
    for part in ("legislation", "tracker_uw", "executive", "news", "state"):
        assert (temp / f"channel-{part}.log").read_text(encoding="utf-8") == f"collectors.{part}: ran\n"
    assert (out.index("collectors.tracker_uw: ran") < out.index("Traceback (most recent call last):")
            < out.index("collectors.executive: ran") < out.index("collectors.news: ran")
            < out.index("collectors.state: ran"))
    assert out.rstrip().endswith("collectors: every part ran; these exited non-zero:\nlitigation 1")
    assert cv.last_line((temp / "channel-litigation.log").read_text(encoding="utf-8")) == f"{RAISED} token={PLANTED}"
    assert cv.channel_crashes(str(temp)) == [("litigation", 1, f"{RAISED} token={PLANTED}")]

    # The Verdict, where the other four wrote their rows and litigation died before it
    # could: red, naming the step and litigation's line, and litigation is not also
    # "unrecorded". The body it writes for the issue carries no credential.
    monkeypatch.setenv("COURTLISTENER_TOKEN", PLANTED)
    _the_others_recorded(live)
    findings = cv.verdict(live, RID, cv.STATE_SLOT, STARTED, "failure", NOW,
                          runner_temp=str(temp), step_outcomes=OUTCOMES)
    assert findings == [JOB_LINE, ("litigation", rs.FAILED, f"exited 1: {RAISED} token={PLANTED}")]
    body = cv.body(findings, RID, cv.STATE_SLOT, URL)
    assert "| job | job | `Run collectors` failed: litigation exited non-zero |" in body
    assert f"| litigation | failed | exited 1: {RAISED} token=[redacted] |" in body
    assert PLANTED not in body


def test_a_channel_that_wrote_its_failed_row_is_named_by_the_row_and_once(tmp_path, live):
    """run_signals.guarded's row carries the exception line scrubbed at the source; the
    step's record of the same crash adds nothing beside it."""
    _record(tmp_path, {"litigation": 1},
            {"litigation": f"Traceback (most recent call last):\n{RAISED} token={PLANTED}\n"})
    _the_others_recorded(live)
    _row(live, "litigation", rs.FAILED, f"{RAISED} token=[redacted]")
    live.commit()
    assert cv.verdict(live, RID, cv.STATE_SLOT, STARTED, "failure", NOW, runner_temp=str(tmp_path),
                      step_outcomes=OUTCOMES) == [
        JOB_LINE, ("litigation", rs.FAILED, f"{RAISED} token=[redacted]")]


def test_a_channel_that_died_before_its_row_is_named_by_the_record_and_not_as_unrecorded(tmp_path, live):
    """The bash-free half of the planted case: the Verdict reads the step's record alone."""
    _record(tmp_path, {"litigation": 1}, {"litigation": f"{RAISED} token={PLANTED}\n"})
    _the_others_recorded(live)
    assert cv.verdict(live, RID, cv.STATE_SLOT, STARTED, "failure", NOW, runner_temp=str(tmp_path),
                      step_outcomes=OUTCOMES) == [
        JOB_LINE, ("litigation", rs.FAILED, f"exited 1: {RAISED} token={PLANTED}")]


def test_a_part_that_writes_no_row_is_named_by_the_steps_record(tmp_path, live):
    """tracker_uw is a part of the step but not a channel: it writes no row, and its
    crash is named by its exit and its log's last line all the same."""
    _record(tmp_path, {"tracker_uw": 1}, {"tracker_uw": "RuntimeError: the UW tracker page changed\n"})
    _the_others_recorded(live)
    _row(live, "litigation", rs.OK, "40 OK replies")
    live.commit()
    assert cv.verdict(live, RID, cv.STATE_SLOT, STARTED, "failure", NOW, runner_temp=str(tmp_path),
                      step_outcomes=OUTCOMES) == [
        ("job", "job", "`Run collectors` failed: tracker_uw exited non-zero"),
        ("tracker_uw", rs.FAILED, "exited 1: RuntimeError: the UW tracker page changed")]


def test_the_steps_record_reads_each_failed_parts_exit_and_last_line(tmp_path):
    (tmp_path / "channels").write_text(
        "legislation 0\ntracker_uw 0\nlitigation 1\nexecutive 0\nnews 137\nstate 0\nnot a line\n",
        encoding="utf-8")
    (tmp_path / "channel-litigation.log").write_text("polling\n\nValueError: drop\n\n", encoding="utf-8")
    assert cv.channel_crashes(str(tmp_path)) == [("litigation", 1, "ValueError: drop"), ("news", 137, "")]
    assert cv.channel_crashes(str(tmp_path / "no-such-dir")) == []


@pytest.mark.parametrize("outcomes, files, line", [
    # A step that kept its output: named with its last line.
    ("deps=success collectors=success export=failure commit=skipped",
     {"export.log": "wrote data/bills.json\nTraceback (most recent call last):\nRuntimeError: export died\n"},
     "`Export JSON snapshots` failed: RuntimeError: export died"),
    # A step that did not: named, and pointed at the run's log.
    ("deps=failure collectors=skipped export=skipped commit=skipped", {},
     "`Install dependencies` failed; its output is in the run's log"),
    ("checkout=failure", {}, "`actions/checkout@v4` failed; its output is in the run's log"),
    # The collectors step: the parts that exited non-zero, each of whose lines is its own
    # finding. With no record of its parts, it is pointed at the run's log.
    ("collectors=failure export=skipped commit=skipped",
     {"channels": "legislation 0\nlitigation 1\nexecutive 0\nnews 2\nstate 0\n"},
     "`Run collectors` failed: litigation, news exited non-zero"),
    ("collectors=failure", {}, "`Run collectors` failed; its output is in the run's log"),
    # The first failed step in run order, whatever the order of the pairs.
    ("commit=failure export=failure", {"export.log": "boom\n"}, "`Export JSON snapshots` failed: boom"),
    # No outcome names a failure: the status alone, as before.
    ("", {}, "an earlier step ended `failure`"),
    ("collectors=success", {}, "an earlier step ended `failure`"),
])
def test_the_job_line_names_the_first_failed_step(tmp_path, outcomes, files, line):
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    assert cv.job_findings("failure", outcomes, str(tmp_path)) == [("job", "job", line)]


def test_a_green_job_has_no_job_line(tmp_path):
    (tmp_path / "channels").write_text("litigation 1\n", encoding="utf-8")
    assert cv.job_findings("success", "collectors=failure", str(tmp_path)) == []


def test_the_step_runs_every_part_through_part_and_each_channel_is_one():
    """A collector added to the step outside `part` would end it at a crash again, and
    one whose name is not its module would be named wrongly in the Verdict."""
    script = _named("Run collectors")["run"]
    calls = re.findall(r"^\s*part (\S+) python -m collectors\.(\S+)", script, re.M)
    assert [name for name, _ in calls] == list(PARTS)
    assert all(name == module for name, module in calls)
    assert set(rs.CHANNELS) <= set(PARTS)
    bare = [ln for ln in script.splitlines() if "python -m collectors." in ln and not ln.strip().startswith("part ")]
    assert bare == []


def test_the_verdicts_steps_are_collect_ymls_and_its_env_carries_each_outcome():
    steps = _steps()
    ids = [s.get("id") for s in steps]
    verdict_at = ids.index("verdict")
    for sid, name in cv.STEPS:
        assert sid in ids[:verdict_at], sid                       # every one runs before the Verdict
        step = steps[ids.index(sid)]
        assert name in (step.get("name"), step.get("uses")), (sid, name)
    assert [i for i in ids[:verdict_at] if i in dict(cv.STEPS)] == [sid for sid, _ in cv.STEPS]
    env = steps[verdict_at]["env"]
    # The template, before Actions fills each `${{ steps.<id>.outcome }}` with a word.
    pairs = re.findall(r"(\w+)=\$\{\{\s*steps\.(\w+)\.outcome\s*\}\}", env["STEP_OUTCOMES"])
    assert [a for a, _ in pairs] == [b for _, b in pairs] == [sid for sid, _ in cv.STEPS]
    # Its scrub covers every credential the collectors carry, since the line is their output.
    assert set(cv.run_signals.CREDENTIAL_ENV) <= set(env)

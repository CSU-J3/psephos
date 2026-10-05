"""collect.yml names the step that failed (Corey, 2026-10-05).

The 2026-10-04 06:17Z slot's run (37201585654) died in the litigation collector on a Turso
drop, and the Verdict's only line for it was "an earlier step ended `failure`". It went
unread for a day and a half. The collectors step now keeps its output at
$RUNNER_TEMP/collectors.log and the command that failed at $RUNNER_TEMP/collectors.failed,
and the Verdict names the step, the command and the log's last line, scrubbed.

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
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools import collect_verdict as cv  # noqa: E402

PLANTED = "PLANTED-courtlistener-token-0123456789abcdef"
RAISED = "ValueError: Hrana: `http error: `connection closed before message completed``"
# Litigation raises the 2026-10-04 run's exception, the planted credential in its message;
# every other collector says it ran and exits 0. `exec`, so the step's own command is the
# one that fails, as `python -m collectors.litigation` did.
STUB = ('#!/usr/bin/env bash\n'
        'case "$2" in\n'
        '  collectors.litigation)\n'
        '    exec "$REAL_PYTHON" -c \'import os\n'
        'raise ValueError("Hrana: `http error: `connection closed before message completed`` '
        'token=" + os.environ["COURTLISTENER_TOKEN"])\' ;;\n'
        '  *) echo "$2: ran" ;;\n'
        'esac\n')
OUTCOMES = "checkout=success python=success deps=success collectors=failure export=skipped commit=skipped"


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


@needs_bash
def test_a_planted_collector_exception_is_named_by_its_step_command_and_last_line(tmp_path, monkeypatch):
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
    assert r.returncode != 0, r.stdout + r.stderr
    # bash -e still ends the group at the first failure: the collectors after it never ran.
    assert "collectors.tracker_uw: ran" in r.stdout and "collectors.executive" not in r.stdout
    assert (temp / "collectors.failed").read_text(encoding="utf-8").strip() == "python -m collectors.litigation"
    log = (temp / "collectors.log").read_text(encoding="utf-8")
    assert "Traceback (most recent call last):" in log and "collectors.legislation: ran" in log
    assert cv.last_line(log) == f"{RAISED} token={PLANTED}"

    # The Verdict's job line names the step, the command and that line; the body it writes
    # for the issue carries no credential.
    monkeypatch.setenv("COURTLISTENER_TOKEN", PLANTED)
    findings = cv.job_findings("failure", OUTCOMES, str(temp))
    assert findings == [("job", "job", "`Run collectors` failed at `python -m collectors.litigation`: "
                                       f"{RAISED} token={PLANTED}")]
    body = cv.body(findings, "37201585654", "17 6 * * *", "https://github.com/CSU-J3/psephos/actions/runs/37201585654")
    assert ("| job | job | `Run collectors` failed at `python -m collectors.litigation`: "
            f"{RAISED} token=[redacted] |") in body
    assert PLANTED not in body


@pytest.mark.parametrize("outcomes, files, line", [
    # A step that kept its output: named with its last line.
    ("deps=success collectors=success export=failure commit=skipped",
     {"export.log": "wrote data/bills.json\nTraceback (most recent call last):\nRuntimeError: export died\n"},
     "`Export JSON snapshots` failed: RuntimeError: export died"),
    # A step that did not: named, and pointed at the run's log.
    ("deps=failure collectors=skipped export=skipped commit=skipped", {},
     "`Install dependencies` failed; its output is in the run's log"),
    ("checkout=failure", {}, "`actions/checkout@v4` failed; its output is in the run's log"),
    # The first failed step in run order, whatever the order of the pairs.
    ("commit=failure collectors=failure", {"collectors.log": "boom\n"}, "`Run collectors` failed: boom"),
    # No outcome names a failure: the status alone, as before.
    ("", {}, "an earlier step ended `failure`"),
    ("collectors=success", {}, "an earlier step ended `failure`"),
])
def test_the_job_line_names_the_first_failed_step(tmp_path, outcomes, files, line):
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    assert cv.job_findings("failure", outcomes, str(tmp_path)) == [("job", "job", line)]


def test_a_green_job_has_no_job_line(tmp_path):
    (tmp_path / "collectors.log").write_text("ValueError: stale\n", encoding="utf-8")
    assert cv.job_findings("success", "collectors=failure", str(tmp_path)) == []


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

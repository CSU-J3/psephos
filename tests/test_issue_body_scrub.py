"""Every issue body every lane posts goes through the one scrub (unit 99, Corey,
2026-09-28).

Actions masks secrets in the run LOG. It does not mask text a step sends to the Issues
API, and the three standing-issue steps post raw tool output: collect's Verdict body,
coverage_audit's whole output with its traceback, dom-checks' check captures and server
log. A libsql error can name the database URL in any of them.

TWO HALVES.

  * STRUCTURAL: every step in every workflow that comments on or opens an issue (or a PR,
    or posts through `gh api`) uses `--body-file`, runs tools/scrub_issue_body.py on that
    same file BEFORE the first post, and carries in its env every credential its
    workflow maps from secrets, so the scrub knows the values. A new lane that posts
    without it fails here.
  * FUNCTIONAL: each lane's REAL issue-step script, taken from its workflow and run under
    bash, with a stand-in `gh` on PATH that captures what it would post. FAKE credential
    values are planted where each lane's raw output could carry them -- the audit's
    traceback with a libsql error naming the database URL, dom-checks' server log and
    check captures, a collect verdict body -- bare, and inside URLs as query parameters.
    The captured body must hold none of them and no query string. POSITIVE CONTROL: the
    same script with its scrub line removed must post them, so a clean result means the
    scrub removed them, not that they never arrived.

FAKE VALUES ONLY (the secret-audit rule): no real credential is read, set or compared.
The functional half needs a POSIX bash (Actions' ubuntu runner; Git Bash locally) and is
skipped where there is none.

Run:  pytest tests/test_issue_body_scrub.py
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

import scrub  # noqa: E402

WORKFLOWS = REPO / ".github" / "workflows"
SCRUB_TOOL = '"$GITHUB_WORKSPACE/tools/scrub_issue_body.py"'
POSTING = re.compile(r"\bgh\s+(?:(?:issue|pr)\s+(?:comment|create|edit)\b|api\b[^\n]*"
                     r"(?:comments|issues))")
BODY_FILE = re.compile(r"--body-file\s+(\"[^\"]+\"|'[^']+'|\S+)")
INLINE_BODY = re.compile(r"(?:^|\s)(?:--body|-b)(?=\s|=|$)"
                         r"|(?:^|\s)(?:-f|-F|--field|--raw-field)\s+body=")
SECRET_REF = re.compile(r"\$\{\{\s*secrets\.([A-Z0-9_]+)\s*\}\}")


# --- the structural half -----------------------------------------------------------------

def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _steps(wf: dict):
    for job_name, job in (wf.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            yield job_name, job, step


def _credential_env(wf: dict) -> dict[str, str]:
    """Every CREDENTIAL_ENV name the workflow maps from a secret, anywhere (job env or a
    step's), with its expression."""
    out = {}
    envs = [wf.get("env") or {}]
    for _, job, step in _steps(wf):
        envs += [job.get("env") or {}, step.get("env") or {}]
    for env in envs:
        for k, v in env.items():
            if k in scrub.CREDENTIAL_ENV and SECRET_REF.search(str(v)):
                out.setdefault(k, str(v))
    return out


def _unquote(arg: str) -> str:
    return arg.strip().strip('"').strip("'")


def violations(wf: dict, name: str) -> list[str]:
    """What is wrong with a workflow's posting steps. Empty when every one scrubs."""
    creds = _credential_env(wf)
    out = []
    for _, _, step in _steps(wf):
        script = step.get("run") or ""
        lines = script.splitlines()
        posts = [i for i, ln in enumerate(lines)
                 if POSTING.search(ln.split("#", 1)[0])]
        if not posts:
            continue
        label = f"{name}: {step.get('name')!r}"
        scrubbed = {}
        for i, ln in enumerate(lines):
            code = ln.split("#", 1)[0]
            if "tools/scrub_issue_body.py" in code:
                if SCRUB_TOOL not in code or not re.search(r"\bpython3?\b", code):
                    out.append(f"{label}: the scrub must be `python3 {SCRUB_TOOL} FILE`")
                for arg in code.split(SCRUB_TOOL, 1)[-1].split():
                    scrubbed.setdefault(_unquote(arg), i)
        for i in posts:
            code = lines[i].split("#", 1)[0]
            if INLINE_BODY.search(code):
                out.append(f"{label}: posts an inline body; use --body-file")
            files = [_unquote(a) for a in BODY_FILE.findall(code)]
            if not files:
                out.append(f"{label}: posts without --body-file")
            for f in files:
                if f not in scrubbed:
                    out.append(f"{label}: posts {f} without scrubbing it")
                elif scrubbed[f] > i:
                    out.append(f"{label}: scrubs {f} only after posting it")
        env = step.get("env") or {}
        for k, v in creds.items():
            if str(env.get(k)) != v:
                out.append(f"{label}: env lacks {k}: {v}, so the scrub cannot know it")
    return out


def test_every_posting_step_in_every_workflow_scrubs_first():
    found = set()
    problems = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        wf = _load(path)
        if any(POSTING.search(s.get("run") or "") for _, _, s in _steps(wf)):
            found.add(path.name)
        problems += violations(wf, path.name)
    assert problems == []
    # Not vacuous: the three standing-issue lanes are found as posters.
    assert found == {"collect.yml", "audit.yml", "dom-checks.yml"}


@pytest.mark.parametrize("script, env, expected", [
    # no scrub at all
    ('gh issue create --title "$TITLE" --body-file body.md\n', {}, "posts body.md without scrubbing it"),
    # an inline body
    ('gh issue comment 1 --body "$TEXT"\n', {}, "posts an inline body"),
    # scrubbed after posting
    ('gh issue comment 1 --body-file b.md\npython3 ' + SCRUB_TOOL + ' b.md\n', {},
     "scrubs b.md only after posting it"),
    # scrubbed a different file
    ('python3 ' + SCRUB_TOOL + ' a.md\ngh issue create --body-file b.md\n', {},
     "posts b.md without scrubbing it"),
    # the credential missing from the step's env
    ('python3 ' + SCRUB_TOOL + ' b.md\ngh issue create --body-file b.md\n', {},
     "env lacks TURSO_DATABASE_URL"),
    # posting through gh api
    ('gh api repos/x/y/issues/1/comments -f body="$TEXT"\n', {}, "posts an inline body"),
])
def test_the_checker_fails_a_step_that_posts_unscrubbed(script, env, expected):
    wf = {"jobs": {"j": {"steps": [
        {"name": "use", "env": {"TURSO_DATABASE_URL": "${{ secrets.TURSO_DATABASE_URL }}"},
         "run": "true"},
        {"name": "post", "env": env, "run": script}]}}}
    got = violations(wf, "synthetic.yml")
    assert any(expected in v for v in got), got


def test_a_scrubbing_step_with_its_credentials_passes_the_checker():
    wf = {"jobs": {"j": {"steps": [
        {"name": "use", "env": {"TURSO_DATABASE_URL": "${{ secrets.TURSO_DATABASE_URL }}"},
         "run": "true"},
        {"name": "post", "env": {"TURSO_DATABASE_URL": "${{ secrets.TURSO_DATABASE_URL }}"},
         "run": 'python3 ' + SCRUB_TOOL + ' "$B"\ngh issue create --body-file "$B"\n'}]}}}
    assert violations(wf, "synthetic.yml") == []


# --- the scrub itself ----------------------------------------------------------------------

def test_scrub_body_keeps_the_layout_and_the_endpoints():
    body = ("cc @CSU-J3\n\n```\nTraceback (most recent call last):\n"
            "  GET https://api.legiscan.com/?key=FAKEFAKEFAKE1234&op=getBill\n"
            "    indented   line   kept\n```\n")
    out = scrub.scrub_body(body, ())
    assert out == ("cc @CSU-J3\n\n```\nTraceback (most recent call last):\n"
                   "  GET https://api.legiscan.com/\n"
                   "    indented   line   kept\n```\n")


def test_the_tool_scrubs_in_place_and_refuses_a_missing_file(tmp_path, monkeypatch, capsys):
    from tools import scrub_issue_body as tool
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "FAKETOOLTOKEN-0123456789")
    body = tmp_path / "b.md"
    body.write_bytes(b"token FAKETOOLTOKEN-0123456789 here\nhttps://x.invalid/p?q=1\n")
    assert tool.main([str(body)]) == 0
    assert body.read_bytes() == b"token [redacted] here\nhttps://x.invalid/p\n"
    out = capsys.readouterr().out
    assert "FAKETOOLTOKEN" not in out and "1 credential value(s)" in out
    assert tool.main([str(tmp_path / "missing.md")]) == 1
    assert tool.main([]) == 2


# --- the functional half: the real step scripts ----------------------------------------------

FAKE = {
    "CONGRESS_API_KEY": "FAKECONGRESSKEY-0123456789abcdefghij",
    "LEGISCAN_API_KEY": "FAKELEGISCANKEY-9876543210fedcba",
    "COURTLISTENER_TOKEN": "FAKECOURTLISTENERTOKEN-00112233445566778899",
    "TURSO_DATABASE_URL": "libsql://psephos-fakedb-0000.example-region.turso.io",
    "TURSO_AUTH_TOKEN": "FAKETURSOWRITETOKEN.eyJ3cml0ZSI6dHJ1ZX0.0123456789",
}
# The audit and dom-checks lanes run on the READ token, a different value under the same
# variable name.
FAKE_SECRET = {**FAKE, "TURSO_READ_TOKEN": "FAKETURSOREADTOKEN.eyJyZWFkIjp0cnVlfQ.9876543210"}
TURSO_HOST = "psephos-fakedb-0000.example-region.turso.io"
KEYED_URLS = (
    "https://api.congress.gov/v3/bill/119/hr/22?api_key=" + FAKE["CONGRESS_API_KEY"] + "&format=json",
    "https://api.legiscan.com/?key=" + FAKE["LEGISCAN_API_KEY"] + "&op=getSessionList",
    "https://www.courtlistener.com/api/rest/v4/dockets/?token=" + FAKE["COURTLISTENER_TOKEN"],
)
QUERY_MARKS = ("api_key=", "?key=", "?token=", "authToken=")


def _bash() -> str | None:
    b = shutil.which("bash")
    if not b or "system32" in b.lower():      # the WSL launcher is not a POSIX bash here
        return None
    return b


needs_bash = pytest.mark.skipif(_bash() is None, reason="no POSIX bash on this machine")


FLAG_STEP = "Comment new recheck flags on their standing issue"
FAULT_STEP = "Report a recheck-flags run that could not run"
# Every posting step a functional case below runs, by workflow; the first is the default.
# A workflow not listed must hold exactly one. A new poster fails here until it is named
# here and given a case: the one-poster tripwire, kept as a registry since audit.yml
# gained its flag steps (2026-09-29).
POSTERS = {"audit.yml": ("Raise or update the standing issue", FLAG_STEP, FAULT_STEP)}


def _posting_step(workflow: str, name: str | None = None) -> dict:
    wf = _load(WORKFLOWS / workflow)
    steps = [s for _, _, s in _steps(wf) if POSTING.search(s.get("run") or "")]
    if workflow in POSTERS:
        assert sorted(s.get("name") for s in steps) == sorted(POSTERS[workflow]), workflow
        name = name or POSTERS[workflow][0]
        steps = [s for s in steps if s.get("name") == name]
    assert len(steps) == 1, (workflow, name)
    return steps[0]


def _libsql_traceback(url: str, token: str) -> str:
    """What a libsql failure looks like in a captured output: the URL, its host alone, and
    the URL with the token as a query parameter."""
    return (
        "Traceback (most recent call last):\n"
        '  File "/home/runner/work/psephos/psephos/db.py", line 430, in connect\n'
        "    raw = libsql.connect(database=url, auth_token=token)\n"
        f"ValueError: Hrana: `api error: `status=502 Bad Gateway, url={url}/v2/pipeline`, "
        f'body={{"error":"upstream forward failed"}}``\n'
        f"libsql: failed to open {url}?authToken={token} (host {TURSO_HOST}, token {token})\n"
        "  also tried " + " ".join(KEYED_URLS) + "\n")


def _env_for(step: dict, runner_temp: Path, capture: Path, shims: Path,
             overrides: dict) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in scrub.CREDENTIAL_ENV and not k.startswith(("GH_", "GITHUB_"))}
    for k, v in (step.get("env") or {}).items():
        m = SECRET_REF.search(str(v))
        if m:
            env[k] = FAKE_SECRET.get(m.group(1), "fake-" + m.group(1).lower())
        elif "${{" in str(v):
            env[k] = ""
        else:
            env[k] = str(v)
    env.update({
        "GITHUB_WORKSPACE": REPO.as_posix(), "RUNNER_TEMP": runner_temp.as_posix(),
        "GITHUB_REF_NAME": "main", "GITHUB_RUN_ID": "12345",
        "RUN_URL": "https://github.com/CSU-J3/psephos/actions/runs/12345",
        "GH_CAPTURE": capture.as_posix(),
        "PATH": str(shims) + os.pathsep + os.environ.get("PATH", ""),
    })
    env.update(overrides)
    return env


def _shims(bin_dir: Path) -> None:
    bin_dir.mkdir()
    (bin_dir / "gh").write_bytes(
        b"#!/usr/bin/env bash\n"
        b"# test stand-in: `issue list` answers GH_LIST_NUM; a post copies its body file.\n"
        b'if [ "$1 $2" = "issue list" ]; then [ -n "$GH_LIST_NUM" ] && echo "$GH_LIST_NUM"; exit 0; fi\n'
        b'echo "$1 $2" > "$GH_CAPTURE.cmd"\n'
        b'while [ $# -gt 0 ]; do\n'
        b'  if [ "$1" = "--body-file" ]; then cp "$2" "$GH_CAPTURE"; fi\n'
        b'  shift\n'
        b'done\n')
    (bin_dir / "python3").write_bytes(
        b"#!/usr/bin/env bash\n"
        + f'exec "{Path(sys.executable).as_posix()}" "$@"\n'.encode("utf-8"))
    # `python -m tools.recheck_flags` would read the database: the stand-in writes the
    # planted body (FLAGS_PLANT, or nothing) to its --comment-body path instead.
    (bin_dir / "python").write_bytes(
        b"#!/usr/bin/env bash\n"
        b'if [ "$1 $2" = "-m tools.recheck_flags" ]; then\n'
        b'  while [ $# -gt 0 ]; do\n'
        b'    if [ "$1" = "--comment-body" ]; then\n'
        b'      if [ -n "$FLAGS_PLANT" ]; then cp "$FLAGS_PLANT" "$2"; else : > "$2"; fi\n'
        b'    fi\n'
        b'    shift\n'
        b'  done\n'
        b'  exit 0\n'
        b'fi\n'
        + f'exec "{Path(sys.executable).as_posix()}" "$@"\n'.encode("utf-8"))
    for f in ("gh", "python3", "python"):
        (bin_dir / f).chmod(0o755)


def _run_step(tmp_path: Path, workflow: str, overrides: dict, *, drop_scrub=False,
              list_num: str = "", step_name: str | None = None) -> tuple[str, str]:
    """The workflow's real posting script under bash; returns (posted body, gh command)."""
    step = _posting_step(workflow, step_name)
    script = step["run"]
    if drop_scrub:                                   # the positive control
        script = "\n".join(ln for ln in script.splitlines()
                           if "tools/scrub_issue_body.py" not in ln) + "\n"
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    runner_temp = tmp_path / "runner_temp"
    runner_temp.mkdir(exist_ok=True)
    bin_dir = tmp_path / "bin"
    if not bin_dir.exists():
        _shims(bin_dir)
    capture = tmp_path / "posted.md"
    if capture.exists():
        capture.unlink()
    script_file = tmp_path / "step.sh"
    script_file.write_bytes(script.encode("utf-8"))
    env = _env_for(step, runner_temp, capture, bin_dir, overrides)
    env["GH_LIST_NUM"] = list_num
    r = subprocess.run([_bash(), "--noprofile", "--norc", "-eo", "pipefail",
                        script_file.as_posix()], cwd=work, env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert capture.exists(), (r.stdout, r.stderr)
    posted = capture.read_bytes().decode("utf-8")
    cmd = Path(str(capture) + ".cmd").read_text(encoding="utf-8").strip()
    return posted, cmd


def _needles(step: dict) -> tuple[str, ...]:
    """The credential values this step's run carries (from its env's secret refs), the
    database host, and every key that rides in a URL's query string."""
    vals = []
    for v in (step.get("env") or {}).values():
        m = SECRET_REF.search(str(v))
        if m and m.group(1) in FAKE_SECRET and m.group(1) != "GITHUB_TOKEN":
            vals.append(FAKE_SECRET[m.group(1)])
    return (*vals, TURSO_HOST, FAKE["CONGRESS_API_KEY"], FAKE["LEGISCAN_API_KEY"],
            FAKE["COURTLISTENER_TOKEN"])


def _plant_audit(tmp_path: Path) -> None:
    (tmp_path / "work").mkdir(exist_ok=True)
    (tmp_path / "work" / "audit.out").write_text(
        "coverage_audit: 45 cases, 43 seed keys\n\n"
        + _libsql_traceback(FAKE["TURSO_DATABASE_URL"], FAKE_SECRET["TURSO_READ_TOKEN"]),
        encoding="utf-8")


def _plant_dom(tmp_path: Path) -> None:
    rt = tmp_path / "runner_temp"
    rt.mkdir(exist_ok=True)
    tb = _libsql_traceback(FAKE["TURSO_DATABASE_URL"], FAKE_SECRET["TURSO_READ_TOKEN"])
    (rt / "server.log").write_text("  ▲ Next.js\n  ⨯ Error: LibsqlError: SERVER_ERROR\n"
                                   + tb, encoding="utf-8")
    for name in ("gates", "encodings", "layout", "attribution", "dated"):
        (rt / f"{name}.out").write_text(f"{name}: FAIL\n" + tb, encoding="utf-8")


def _plant_collect(tmp_path: Path) -> None:
    rt = tmp_path / "runner_temp"
    rt.mkdir(exist_ok=True)
    (rt / "collect-verdict.md").write_text(
        "cc @CSU-J3\n\n**collect red** -- run [12345](https://example.invalid), slot `17 0 * * *`\n\n"
        "| channel | class | evidence |\n|---|---|---|\n"
        f"| legislation | credential failure | raw {FAKE['CONGRESS_API_KEY']} |\n"
        f"| state | no OK replies | {FAKE['LEGISCAN_API_KEY']} {FAKE['COURTLISTENER_TOKEN']} |\n"
        "| job | job | " + _libsql_traceback(FAKE["TURSO_DATABASE_URL"],
                                            FAKE["TURSO_AUTH_TOKEN"]).replace("\n", " ")
        + " |\n", encoding="utf-8")


CASES = [
    # (workflow, planting, env overrides, what the body must still carry)
    ("audit.yml", _plant_audit, {}, ("`coverage_audit` exited non-zero", "db.py")),
    ("dom-checks.yml", _plant_dom, {"PREFLIGHT": "failure"},
     ("CANNOT RUN", "<summary>server log</summary>")),
    ("dom-checks.yml", _plant_dom,
     {"PREFLIGHT": "success", "GATES_RC": "1", "ENCODINGS_RC": "1", "LAYOUT_RC": "1",
      "ATTRIBUTION_RC": "1", "DATED_RC": "1"},
     ("PAGE FAILED", "<summary>assert-dated (exit 1)</summary>")),
    ("collect.yml", _plant_collect, {"SLOT": "17 0 * * *"},
     ("| legislation | credential failure |",)),
    ("collect.yml", lambda p: None, {"SLOT": "17 0 * * *"},      # the verdict wrote nothing
     ("The verdict wrote no body",)),
]


@needs_bash
@pytest.mark.parametrize("workflow, plant, overrides, keeps", CASES,
                         ids=["audit", "dom-cannot-run", "dom-page-failed", "collect",
                              "collect-fallback"])
def test_no_planted_credential_survives_a_lanes_real_issue_step(
        tmp_path, workflow, plant, overrides, keeps):
    step = _posting_step(workflow)
    plant(tmp_path)
    posted, cmd = _run_step(tmp_path, workflow, overrides)
    assert cmd == "issue create"
    assert posted.startswith("cc @CSU-J3")
    for text in keeps:
        assert text in posted, text                  # the body still says what it said
    for needle in _needles(step):
        assert needle not in posted
    for mark in QUERY_MARKS:
        assert mark not in posted
    if plant is not _plant_collect and workflow != "collect.yml":
        assert "https://api.legiscan.com/" in posted  # the endpoint survives, its query not
    # A reused issue is commented on through the same scrubbed file.
    posted2, cmd2 = _run_step(tmp_path, workflow, overrides, list_num="7")
    assert cmd2 == "issue comment" and posted2 == posted


@needs_bash
@pytest.mark.parametrize("workflow, plant, overrides", [
    ("audit.yml", _plant_audit, {}),
    ("dom-checks.yml", _plant_dom, {"PREFLIGHT": "failure"}),
    ("collect.yml", _plant_collect, {"SLOT": "17 0 * * *"}),
], ids=["audit", "dom-checks", "collect"])
def test_positive_control_without_the_scrub_the_planted_values_are_posted(
        tmp_path, workflow, plant, overrides):
    """The same scripts with the scrub line removed post the database host and the
    planted keys: the clean results above mean the scrub removed them."""
    plant(tmp_path)
    posted, _ = _run_step(tmp_path, workflow, overrides, drop_scrub=True)
    assert TURSO_HOST in posted
    assert any(m in posted for m in QUERY_MARKS)


# --- the recheck flags' step (audit.yml, 2026-09-29) ---------------------------------------

def _plant_flags(tmp_path: Path) -> Path:
    """What the flag tool's body could carry at worst: docket text quoting a URL with a
    key in its query, and a libsql error line."""
    body = tmp_path / "flags-plant.md"
    body.write_text(
        "cc @CSU-J3\n\n**Recheck flag** -- 1 new order-like entry\n\n"
        "| entry | filed | gate | docket | text |\n|---|---|---|---|---|\n"
        "| 93145 | 2026-09-29 | `g` | 71499795 | ORDER see " + " ".join(KEYED_URLS) + " |\n\n"
        + _libsql_traceback(FAKE["TURSO_DATABASE_URL"], FAKE_SECRET["TURSO_READ_TOKEN"])
        + "\n<!-- recheck-flags: 93145 -->\n", encoding="utf-8")
    return body


@needs_bash
def test_the_flag_steps_body_is_scrubbed_before_it_is_posted(tmp_path):
    step = _posting_step("audit.yml", FLAG_STEP)
    plant = _plant_flags(tmp_path)
    posted, cmd = _run_step(tmp_path, "audit.yml", {"FLAGS_PLANT": plant.as_posix()},
                            step_name=FLAG_STEP)
    assert cmd == "issue create"
    assert posted.startswith("cc @CSU-J3") and "<!-- recheck-flags: 93145 -->" in posted
    for needle in _needles(step):
        assert needle not in posted
    for mark in QUERY_MARKS:
        assert mark not in posted
    posted2, cmd2 = _run_step(tmp_path, "audit.yml", {"FLAGS_PLANT": plant.as_posix()},
                              step_name=FLAG_STEP, list_num="7")
    assert cmd2 == "issue comment" and posted2 == posted
    # The positive control: without the scrub line the planted host is posted.
    raw, _ = _run_step(tmp_path, "audit.yml", {"FLAGS_PLANT": plant.as_posix()},
                       step_name=FLAG_STEP, drop_scrub=True)
    assert TURSO_HOST in raw


@needs_bash
def test_the_flag_step_posts_nothing_when_there_are_no_new_flags(tmp_path):
    step = _posting_step("audit.yml", FLAG_STEP)
    for d in ("work", "runner_temp"):
        (tmp_path / d).mkdir()
    _shims(tmp_path / "bin")
    capture = tmp_path / "posted.md"
    script = tmp_path / "step.sh"
    script.write_bytes(step["run"].encode("utf-8"))
    env = _env_for(step, tmp_path / "runner_temp", capture, tmp_path / "bin", {"FLAGS_PLANT": ""})
    r = subprocess.run([_bash(), "--noprofile", "--norc", "-eo", "pipefail", script.as_posix()],
                       cwd=tmp_path / "work", env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "no new recheck flags" in r.stdout
    assert not capture.exists()


def test_the_flag_steps_can_never_turn_the_audit_red():
    for name in (FLAG_STEP, FAULT_STEP):
        step = _posting_step("audit.yml", name)
        assert step.get("continue-on-error") is True, name
        assert "!cancelled()" in str(step.get("if")), name
        assert 0 < int(step.get("timeout-minutes", 0)) <= 3, name   # a hang is a step failure
        assert "fail" not in step["env"]["TITLE"].lower(), name
    wf = _load(WORKFLOWS / "audit.yml")
    job = wf["jobs"]["audit"]
    assert int(job["timeout-minutes"]) >= 2 * 3 + 5                # both bounds fit the job
    assert wf.get("concurrency", {}).get("group") == "audit"
    assert "steps.flags.outcome == 'failure'" in str(_posting_step("audit.yml", FAULT_STEP)["if"])


def test_markers_are_read_only_from_the_workflows_bot():
    run = _posting_step("audit.yml", FLAG_STEP)["run"]
    assert "select(.title == env.TITLE) | select(bot)" in run
    assert '"app/github-actions", "github-actions", "github-actions[bot]"' in run
    assert run.count("select(bot)") == 3                           # the issue, its body, comments


@needs_bash
def test_the_fault_steps_body_is_scrubbed_before_it_is_posted(tmp_path):
    step = _posting_step("audit.yml", FAULT_STEP)
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "flags.out").write_text(
        "Traceback (most recent call last):\n"
        + _libsql_traceback(FAKE["TURSO_DATABASE_URL"], FAKE_SECRET["TURSO_READ_TOKEN"]),
        encoding="utf-8")
    posted, cmd = _run_step(tmp_path, "audit.yml", {}, step_name=FAULT_STEP)
    assert cmd == "issue create"
    assert posted.startswith("cc @CSU-J3") and "could not run" in posted
    for needle in _needles(step):
        assert needle not in posted
    for mark in QUERY_MARKS:
        assert mark not in posted
    posted2, cmd2 = _run_step(tmp_path, "audit.yml", {}, step_name=FAULT_STEP, list_num="7")
    assert cmd2 == "issue comment" and posted2 == posted
    raw, _ = _run_step(tmp_path, "audit.yml", {}, step_name=FAULT_STEP, drop_scrub=True)
    assert TURSO_HOST in raw

"""collect.yml's data commit against a planted concurrent push (Corey, 2026-09-30).

On 2026-09-30 a human push landed while the 00:17Z slot's run (36674320722) was collecting.
The run's bare `git push` was rejected (fetch first), its data commit was lost, and the
verdict went red naming only "an earlier step ended failure". The step now fetches and
retries: it rebases the data commit over a raced commit that touches nothing under data/,
re-runs the export over one that does (carrying this run's tracker artifact across), and
leaves the marker the Verdict names with the evidence line "data commit not pushed" --
written first, so a step that dies mid-repair leaves it too.

Each case runs the step's REAL script, taken from collect.yml, under bash, in a shallow
runner clone of a local bare "origin", after a second clone has pushed the planted commit.
The export re-run is a stub (DATA_EXPORT) that writes a known snapshot and counts its
calls. Needs a POSIX bash and git (Actions' ubuntu runner; Git Bash locally); skipped
without. The Verdict's reading of the marker with the database up is in
tests/test_unit99_verdict.py, beside its other main() cases.
"""
from __future__ import annotations

import os
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

SNAPSHOTS = ["bills", "cases", "executive", "state_bills", "news", "doj_cases", "generated_at"]
STUB_EXPORT = (b"#!/usr/bin/env bash\n"
               b"echo call >> \"$EXPORT_CALLS\"\n"
               b"printf '{\"cases\": \"re-exported over the raced commit\"}\\n' > data/cases.json\n"
               b"printf '{\"generated_at\": \"re-export\"}\\n' > data/generated_at.json\n")
DIED = "data commit not pushed: the step ended before a push landed"


def _bash() -> str | None:
    b = shutil.which("bash")
    if not b or "system32" in b.lower():      # the WSL launcher is not a POSIX bash here
        return None
    return b


needs_bash = pytest.mark.skipif(_bash() is None or shutil.which("git") is None,
                                reason="no POSIX bash or git on this machine")


def _steps() -> dict:
    wf = yaml.safe_load((REPO / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8"))
    return {s.get("name"): s for s in wf["jobs"]["collect"]["steps"]}


def _step_script() -> str:
    return _steps()["Commit data changes"]["run"]


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          capture_output=True, text=True, check=check)


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))


def _runner_clone(w, name: str, branch: str = "main") -> Path:
    """SHALLOW, as actions/checkout's default (fetch-depth 1) is: the rebase and the diff
    against what it raced must work without history past HEAD~1. The run's export has
    already rewritten data/cases.json and the clock."""
    runner = w["tmp"] / name
    _git(w["tmp"], "clone", "-q", "--depth", "1", "--branch", branch,
         w["origin"].resolve().as_uri(), str(runner))
    _write(runner, "data/cases.json", '{"cases": "exported by this run"}\n')
    _write(runner, "data/generated_at.json", '{"generated_at": "this run"}\n')
    return runner


@pytest.fixture()
def world(tmp_path):
    """origin (bare, main), seeded with the seven snapshots and a doc; a runner clone and a
    human clone."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", str(origin))
    _git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "-q", str(origin), str(seed))
    _git(seed, "checkout", "-q", "-b", "main")
    for name in SNAPSHOTS:
        _write(seed, f"data/{name}.json", f'{{"{name}": "seed"}}\n')
    _write(seed, "docs/status.md", "seed\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-q", "-m", "seed")
    _write(seed, "docs/status.md", "seed, again\n")      # history past the shallow clone's reach
    _git(seed, "commit", "-q", "-am", "seed 2")
    _git(seed, "push", "-q", "origin", "main")
    w = {"tmp": tmp_path, "origin": origin}
    w["runner"] = _runner_clone(w, "runner")
    w["human"] = tmp_path / "human"
    _git(tmp_path, "clone", "-q", str(origin), str(w["human"]))
    w["rt"] = tmp_path / "runner_temp"
    w["rt"].mkdir()
    w["calls"] = tmp_path / "export_calls"
    w["stub"] = tmp_path / "export_stub.sh"
    w["stub"].write_bytes(STUB_EXPORT)
    return w


def _race(w, rel: str, text: str | None, branch: str = "main") -> None:
    """A human push of one file (None deletes it), landing before the run's push."""
    if text is None:
        (w["human"] / rel).unlink()
    else:
        _write(w["human"], rel, text)
    _git(w["human"], "add", "-A")
    _git(w["human"], "commit", "-q", "-m", f"human: {rel}")
    _git(w["human"], "push", "-q", "origin", branch)


def _run_step(w, cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "SLOT": "17 0 * * *", "RUNNER_TEMP": str(w["rt"]),
           # Split into words by the step (read -a), so a quote would be a literal character
           # of the path. pytest's tmp paths hold no spaces.
           "DATA_EXPORT": f'bash {w["stub"].as_posix()}', "EXPORT_CALLS": str(w["calls"]),
           "HUMAN": str(w["human"]), "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run([_bash(), "--noprofile", "--norc", "-e", "-c", _step_script()],
                          cwd=cwd or w["runner"], env=env, capture_output=True, text=True)


def _origin_log(w, branch: str = "main") -> list[str]:
    return _git(w["origin"], "log", "--format=%s", branch).stdout.split("\n")[:-1]


def _origin_file(w, rel: str, branch: str = "main") -> str:
    return _git(w["origin"], "show", f"{branch}:{rel}").stdout


def _calls(w) -> int:
    return len(w["calls"].read_text().split()) if w["calls"].exists() else 0


def _marker(w) -> Path:
    return w["rt"] / cv.DATA_COMMIT_MARKER


@needs_bash
def test_the_planted_race_rejects_a_bare_push(world):
    """The positive control: without the retry, the planted push costs the data commit."""
    _race(world, "docs/status.md", "a human's docs commit\n")
    _git(world["runner"], "commit", "-q", "-am", "data: bare")
    assert _git(world["runner"], "push", check=False).returncode != 0


@needs_bash
def test_no_race_pushes_on_the_first_attempt(world):
    r = _run_step(world)
    assert r.returncode == 0, r.stderr
    assert "attempt 1" in r.stdout
    assert _origin_log(world)[0].startswith("data: scheduled collection")
    assert not _marker(world).exists() and _calls(world) == 0


@needs_bash
def test_nothing_to_commit_exits_clean_and_clears_the_marker(world):
    _git(world["runner"], "checkout", "--", "data/cases.json", "data/generated_at.json")
    r = _run_step(world)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "No changes." in r.stdout
    assert _origin_log(world) == ["seed 2", "seed"]
    assert not _marker(world).exists() and _calls(world) == 0


@needs_bash
def test_a_docs_only_race_is_rebased_with_no_export_re_run(world):
    _race(world, "docs/status.md", "a human's docs commit\n")
    r = _run_step(world)
    assert r.returncode == 0, r.stderr
    log = _origin_log(world)
    assert log[0].startswith("data: scheduled collection") and log[1] == "human: docs/status.md"
    assert _origin_file(world, "data/cases.json") == '{"cases": "exported by this run"}\n'
    assert _origin_file(world, "docs/status.md") == "a human's docs commit\n"
    assert _calls(world) == 0 and not _marker(world).exists()


@needs_bash
def test_a_race_touching_data_re_runs_the_export_over_it(world):
    _race(world, "data/doj_cases.json", '{"doj_cases": "a human edited the tracker artifact"}\n')
    r = _run_step(world)
    assert r.returncode == 0, r.stderr
    log = _origin_log(world)
    assert log[0].startswith("data: scheduled collection") and log[1] == "human: data/doj_cases.json"
    assert _calls(world) == 1
    assert _origin_file(world, "data/cases.json") == '{"cases": "re-exported over the raced commit"}\n'
    # This run did not move the tracker artifact, so the human's edit to it survives.
    assert _origin_file(world, "data/doj_cases.json") == '{"doj_cases": "a human edited the tracker artifact"}\n'
    assert not _marker(world).exists()


@needs_bash
def test_the_re_export_carries_this_runs_tracker_artifact_across(world):
    """The export does not write data/doj_cases.json; collectors.tracker_uw does, a step
    earlier. Without the carry the reset put origin's copy back and the push landed with
    it: this run's scrape was lost with no marker."""
    _write(world["runner"], "data/doj_cases.json", '{"doj_cases": "scraped by this run"}\n')
    _race(world, "data/NOTICE.md", "a human's note under data/\n")
    r = _run_step(world)
    assert r.returncode == 0, r.stderr
    log = _origin_log(world)
    assert log[0].startswith("data: scheduled collection") and log[1] == "human: data/NOTICE.md"
    assert _origin_file(world, "data/doj_cases.json") == '{"doj_cases": "scraped by this run"}\n'
    assert _origin_file(world, "data/cases.json") == '{"cases": "re-exported over the raced commit"}\n'
    assert _origin_file(world, "data/NOTICE.md") == "a human's note under data/\n"
    assert _calls(world) == 1 and not _marker(world).exists()


@needs_bash
def test_a_run_whose_only_change_is_the_tracker_artifact_still_pushes_it(world):
    """The re-export reproduces origin byte for byte; the artifact is the whole delta, and
    `No changes after the re-export.` would have dropped it green."""
    _git(world["runner"], "checkout", "--", "data/cases.json", "data/generated_at.json")
    _write(world["runner"], "data/doj_cases.json", '{"doj_cases": "scraped by this run"}\n')
    world["stub"].write_bytes(b"#!/usr/bin/env bash\necho call >> \"$EXPORT_CALLS\"\n")
    _race(world, "data/NOTICE.md", "a human's note under data/\n")
    r = _run_step(world)
    assert r.returncode == 0, r.stderr
    assert "No changes after the re-export." not in r.stdout
    assert _origin_log(world)[0].startswith("data: scheduled collection")
    assert _origin_file(world, "data/doj_cases.json") == '{"doj_cases": "scraped by this run"}\n'
    assert _calls(world) == 1 and not _marker(world).exists()


@needs_bash
def test_a_data_race_whose_re_export_matches_origin_exits_clean(world):
    _write(world["human"], "data/generated_at.json", '{"generated_at": "re-export"}\n')
    _race(world, "data/cases.json", '{"cases": "re-exported over the raced commit"}\n')
    r = _run_step(world)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "No changes after the re-export." in r.stdout
    assert _origin_log(world)[0] == "human: data/cases.json"
    assert _calls(world) == 1 and not _marker(world).exists()


@needs_bash
def test_a_push_that_never_lands_leaves_the_marker_and_the_verdict_names_it(world):
    hook = world["origin"] / "hooks" / "pre-receive"
    hook.write_bytes(b"#!/bin/sh\necho 'rejected by the test' >&2\nexit 1\n")
    hook.chmod(0o755)
    r = _run_step(world)
    assert r.returncode == 0, r.stderr                 # the Verdict turns the run red, not this step
    text = _marker(world).read_text(encoding="utf-8").strip()
    assert text.startswith("data commit not pushed: the push was rejected 3 time(s)")
    # Nothing raced, so the line must not claim a rebase; git's own reason is carried.
    assert "origin had not moved, so the rejection was not a race" in text
    assert "rebased" not in text
    assert "git said: ! [remote rejected] main -> main (pre-receive hook declined)" in text
    assert _origin_log(world) == ["seed 2", "seed"]
    assert _calls(world) == 0
    findings = cv.data_commit_finding(str(world["rt"]))
    assert findings == [("data", "commit", text)]
    body = cv.body(findings, "1", "17 0 * * *", "u")
    assert "| data | commit | data commit not pushed:" in body


@needs_bash
def test_a_failed_export_re_run_leaves_the_marker_not_a_silent_push(world):
    """After `git reset --hard` HEAD equals origin, so a further `git push` succeeds
    trivially ("Everything up-to-date"). The failed re-export must stop the loop and leave
    the marker, never fall through to a push that reports success."""
    _race(world, "data/doj_cases.json", '{"doj_cases": "a human edited the tracker artifact"}\n')
    world["stub"].write_bytes(b"#!/usr/bin/env bash\necho call >> \"$EXPORT_CALLS\"\nexit 3\n")
    r = _run_step(world)
    assert r.returncode == 0, r.stderr
    assert "data commit pushed" not in r.stdout
    assert _calls(world) == 1
    text = _marker(world).read_text(encoding="utf-8").strip()
    assert text.startswith("data commit not pushed: the push was rejected 1 time(s); "
                           "last repair: the export re-run failed; git said: ! [rejected]")
    assert _origin_log(world) == ["human: data/doj_cases.json", "seed 2", "seed"]


@needs_bash
def test_no_repair_follows_the_third_push(world):
    """Every re-export plants a fresh data/ race, so every push is rejected. Two repairs
    are pushed; a third, after the last push, would be work nothing pushes."""
    world["stub"].write_bytes(
        STUB_EXPORT
        + b"n=$(wc -l < \"$EXPORT_CALLS\" | tr -d ' ')\n"
          b"cd \"$HUMAN\" && git pull -q --ff-only"
          b" && printf '{\"news\": \"race %s\"}\\n' \"$n\" > data/news.json"
          b" && git -c user.name=t -c user.email=t@t commit -qam \"human: race $n\""
          b" && git push -q origin main\n")
    _race(world, "data/news.json", '{"news": "race 0"}\n')
    r = _run_step(world)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _calls(world) == 2
    text = _marker(world).read_text(encoding="utf-8").strip()
    assert text.startswith("data commit not pushed: the push was rejected 3 time(s); "
                           "last repair: re-exported on top of a commit that touched data/")
    assert _origin_log(world)[0] == "human: race 2"


@needs_bash
def test_a_step_that_dies_mid_repair_still_leaves_the_marker(world):
    """A raced commit retired a snapshot, so the running job's stage line names a file the
    new tree no longer has, and `git add` ends the step under -e. The marker was written
    first, so the Verdict still names the lost commit, not only the failed step."""
    _race(world, "data/news.json", None)
    r = _run_step(world)
    assert r.returncode != 0
    assert _marker(world).read_text(encoding="utf-8").strip() == DIED
    assert cv.data_commit_finding(str(world["rt"])) == [("data", "commit", DIED)]
    assert _origin_log(world) == ["human: data/news.json", "seed 2", "seed"]


@needs_bash
def test_a_dispatch_on_another_branch_retries_against_that_branch(world):
    """The bare push targets the checked-out branch, so the repair must fetch and rebase
    onto it, not onto main."""
    _git(world["human"], "checkout", "-q", "-b", "feat")
    _git(world["human"], "push", "-q", "origin", "feat")
    runner = _runner_clone(world, "runner-feat", branch="feat")
    _race(world, "docs/status.md", "a human's docs commit on feat\n", branch="feat")
    r = _run_step(world, cwd=runner)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "attempt 2" in r.stdout
    log = _origin_log(world, "feat")
    assert log[0].startswith("data: scheduled collection") and log[1] == "human: docs/status.md"
    assert _origin_log(world, "main") == ["seed 2", "seed"]
    assert not _marker(world).exists()


def test_the_re_export_is_the_export_steps_command_with_its_credentials():
    """Every step case sets DATA_EXPORT, so the production default is only checkable here."""
    steps = _steps()
    export, commit = steps["Export JSON snapshots"], steps["Commit data changes"]
    command = export["run"].split("#")[0].strip()
    assert f"export_cmd=({command})" in commit["run"]
    for k in ("TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"):
        assert commit["env"].get(k) == export["env"][k]


def test_data_commit_finding_reads_the_marker(tmp_path):
    (tmp_path / cv.DATA_COMMIT_MARKER).write_text("data commit not pushed: the push was rejected 3 time(s); "
                                                  "last repair: rebased onto a commit that touched nothing "
                                                  "under data/\n", encoding="utf-8")
    assert cv.data_commit_finding(str(tmp_path))[0][2].startswith("data commit not pushed")
    assert cv.data_commit_finding(str(tmp_path / "nowhere")) == []


def test_main_names_the_lost_commit_even_when_the_database_is_unreachable(tmp_path, monkeypatch):
    (tmp_path / cv.DATA_COMMIT_MARKER).write_text("data commit not pushed: the push was rejected 3 time(s); "
                                                  "last repair: the fetch failed\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("JOB_STATUS", "success")
    monkeypatch.setattr(cv.config, "load_env", lambda *a, **k: None)

    def down(*a, **k):
        raise ValueError("Hrana: api error: status=502 Bad Gateway")

    monkeypatch.setattr(cv.db, "connect", down)
    assert cv.main() == 1
    body = (tmp_path / "collect-verdict.md").read_text(encoding="utf-8")
    assert "| data | commit | data commit not pushed: the push was rejected 3 time(s); last repair: the fetch failed |" in body

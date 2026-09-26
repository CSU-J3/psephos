"""tools/ci_local.py must mirror ci.yml's python and web jobs, step for step.

The entry point's list is a copy, and a copy drifts: that is how "verify with the command
CI runs" was breached twice. This test is the drift alarm. It reads ci.yml and fails when
the two jobs' steps and tools.ci_local.MIRROR disagree in any way -- a step added, removed,
renamed, reordered, its run text, `with:` inputs or working directory changed, a skipped
step's content changed -- and when ci.yml uses a key MIRROR does not model (a step's `if`,
`env`, `shell`, `working-directory` or `continue-on-error`; a job's `env`, `strategy` or
`defaults.run.shell`; a workflow-level `env` or `defaults`). It also fails on a ci.yml job
that is neither mirrored nor declared CI-only.

The first version compared run steps only, and an adversarial review (2026-09-26) showed
five kinds of drift it passed: a new `uses:` step, a step- or workflow-level working
directory, `if:`/`env:`/`shell:`/matrix keys, and work added under a skipped step's name.
"""

from pathlib import Path

import yaml

from tools.ci_local import CI_ONLY_JOBS, MIRROR, STEPS, Setup, Skip, Step, execute, run_steps

CI_YML = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"
MIRRORED = ("python", "web")

STEP_KEYS = {"name", "run", "uses", "with"}
JOB_KEYS = {"runs-on", "timeout-minutes", "defaults", "steps"}


def _ci():
    return yaml.safe_load(CI_YML.read_text(encoding="utf-8"))


def _key(entry):
    """What a MIRROR entry asserts about ci.yml; reasons are this file's, not ci.yml's."""
    if isinstance(entry, Setup):
        return ("setup", entry.job, entry.uses, entry.inputs)
    if isinstance(entry, Skip):
        return ("skip", entry.job, entry.name, entry.run)
    return ("run", entry.job, entry.name, entry.run, entry.cwd)


def _keys_from_ci() -> list[tuple]:
    ci = _ci()
    assert not {"env", "defaults"} & set(ci), "a workflow-level env or defaults changes every step; ci_local does not model it"
    skipped = {(e.job, e.name) for e in MIRROR if isinstance(e, Skip)}
    out: list[tuple] = []
    for job in MIRRORED:
        spec = ci["jobs"][job]
        assert set(spec) <= JOB_KEYS, (job, set(spec) - JOB_KEYS)
        defaults = spec.get("defaults", {})
        assert defaults in ({}, {"run": {"working-directory": defaults.get("run", {}).get("working-directory")}}), (job, defaults)
        cwd = defaults.get("run", {}).get("working-directory", ".")
        for step in spec["steps"]:
            assert set(step) <= STEP_KEYS, (job, step.get("name") or step.get("uses"), set(step) - STEP_KEYS)
            if "uses" in step:
                inputs = tuple(sorted((k, str(v)) for k, v in (step.get("with") or {}).items()))
                out.append(("setup", job, step["uses"], inputs))
            elif (job, step.get("name")) in skipped:
                out.append(("skip", job, step["name"], step["run"].strip()))
            else:
                out.append(("run", job, step["name"], step["run"].strip(), cwd))
    return out


def test_mirror_is_ci_ymls_two_jobs_step_for_step():
    assert [_key(e) for e in MIRROR] == _keys_from_ci()


def test_every_setup_and_skip_says_why():
    assert all(e.reason.strip() for e in MIRROR if isinstance(e, (Setup, Skip)))


def test_every_ci_job_is_mirrored_or_declared_ci_only():
    assert set(_ci()["jobs"]) == set(MIRRORED) | set(CI_ONLY_JOBS)
    assert all(reason.strip() for reason in CI_ONLY_JOBS.values())


def test_the_mirrored_jobs_run_in_ci_ymls_order():
    assert [j for j in _ci()["jobs"] if j in MIRRORED] == list(MIRRORED)
    assert [s.job for s in STEPS] == sorted((s.job for s in STEPS), key=MIRRORED.index)


# The control flow, on a fake executor: two independent jobs, each ending at its first
# failing step, as a GitHub Actions job does.
def test_a_failing_step_ends_its_job_and_not_the_other():
    steps = (
        Step("python", "pytest", "p", "."),
        Step("web", "vitest", "v", "web"),
        Step("web", "tsc", "t", "web"),
        Step("web", "assert-casts", "c", "web"),
    )
    codes = {"p": 0, "v": 0, "t": 2, "c": 0}
    ran: list[str] = []

    def fake(step: Step) -> int:
        ran.append(step.run)
        return codes[step.run]

    results = run_steps(steps, fake)
    assert ran == ["p", "v", "t"]
    assert [code for _, code in results] == [0, 0, 2, None]


# The shell, for real: a multi-line step runs every line under `bash -e` and stops at the
# first failure, as CI's does. Under cmd.exe the first version ran line one and reported 0.
def test_a_multi_line_step_runs_under_bash_e_and_fails_like_ci():
    assert execute(Step("t", "multi", "true\nexit 7\nexit 0", ".")) == 7
    assert execute(Step("t", "errexit", "false\nexit 0", ".")) == 1
    assert execute(Step("t", "ok", "true\ntrue", ".")) == 0


def test_the_steps_run_in_their_jobs_directory():
    assert execute(Step("t", "cwd", "test -f package.json", "web")) == 0
    assert execute(Step("t", "cwd", "test -f package.json", ".")) == 1

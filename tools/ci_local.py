"""Run ci.yml's python and web jobs locally, in ci.yml's order: the one pre-push command.

    python -m tools.ci_local            # from the repo root

WHY IT EXISTS (ruled 2026-09-26). "Verify with the command CI runs" was breached twice:
`npx vitest run` passed where CI's `pnpm test` failed, and a unit ran tsc, `pnpm test` and
pytest but never `assert-casts`, so `main` went red on three double casts in a test file.
Both times a ritual line listing CI's steps had lost to a step someone added. So the list
lives here, once, as MIRROR: every step of ci.yml's `python` and `web` jobs, in order, each
either run, skipped with its reason, or a toolchain setup step. tests/test_ci_local.py
fails the moment ci.yml and MIRROR differ -- a step added, removed, renamed, reordered,
edited, or given a key this file does not model (if, env, shell, working-directory,
continue-on-error, a matrix) -- so a change to either job is a red test until this file
says what to do about it.

HOW IT RUNS a step: its `run:` text, verbatim, under `bash -e`, in the job's working
directory -- the shell ci.yml's steps get on ubuntu-latest (the step log reads
`shell: /usr/bin/bash -e {0}`). Not cmd.exe: under cmd a multi-line `run: |` block runs its
first line only and reports success (adversarial review, 2026-09-26). On Windows the bash
is Git's; the command refuses rather than fall back to another shell. The two jobs are
independent, as in CI: a failing step ends its own job and the other job still runs. The
exit code is 0 only when every run step passed. ci.yml keeps its separate steps, so its
log stays readable step by step.

WHAT IT DOES NOT MIRROR, each declared below with its reason:
  - the `Install dependencies` steps. They provision a fresh runner; here the environment
    is the developer's, and `pnpm install --frozen-lockfile` would rewrite web/node_modules
    under a working session. `pnpm test` still runs pnpm's own dependency-status check,
    which is what the first breach turned on.
  - the toolchain setup steps (`uses:`). Locally the developer's toolchain runs instead.
    Its node and python are compared with the versions ci.yml pins and a difference is
    warned, below; nothing else about it (pnpm's version, the caches) is compared.
  - the `actionlint` job. It downloads a pinned, checksum-verified Linux binary and lints
    the workflows; it stays CI-only.
So a local green is ci.yml's commands passing on this machine's toolchain and working
tree, not a copy of CI's runner.

WHAT IT SAYS ABOUT THAT, as warnings that never change the exit code (ruled 2026-09-26):
  - when the local node or python differs from the version ci.yml pins, compared at the
    pin's own precision -- node-version "22" names a major, python-version "3.12" a
    minor -- read through the same bash the steps run in, so it is the node and python
    the steps will actually get;
  - when web/.next/types exists. web/tsconfig.json includes `.next/types/**/*.ts`, gitignored
    build output that declares globals (PageProps, LayoutProps); local tsc reads it and
    CI's fresh checkout has none, so a page leaning on it passes here and fails there.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Union

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Step:
    """A run step this command runs."""

    job: str  # the ci.yml job key
    name: str  # the ci.yml step name
    run: str  # the ci.yml run text, verbatim
    cwd: str  # the job's working directory, relative to the repo root ("." for the root)


@dataclass(frozen=True)
class Skip:
    """A run step this command does not run. Keyed on its run text too, so a skip cannot
    outlive the content it excuses."""

    job: str
    name: str
    run: str
    reason: str


@dataclass(frozen=True)
class Setup:
    """A `uses:` step: toolchain or checkout, never run here."""

    job: str
    uses: str
    inputs: tuple[tuple[str, str], ...]  # the step's `with:`, as sorted (key, value) pairs
    reason: str


Entry = Union[Step, Skip, Setup]

_SETUP = "installs a toolchain on a fresh runner; locally the developer's runs, its version not compared"
_SETUP_WARNED = (
    "installs a toolchain on a fresh runner; locally the developer's runs, and a version off this pin "
    "is warned (limits), never failed"
)
_CHECKOUT = "checks the commit out on a fresh runner; locally the working tree is what runs"
_INSTALL = "provisions a fresh runner; would rewrite the developer's environment mid-session"

# Every step of ci.yml's python and web jobs, in ci.yml's order.
MIRROR: tuple[Entry, ...] = (
    Setup("python", "actions/checkout@v4", (), _CHECKOUT),
    Setup("python", "actions/setup-python@v5", (("python-version", "3.12"),), _SETUP_WARNED),
    Skip("python", "Install dependencies",
         "python -m pip install --upgrade pip\npip install -r requirements-dev.txt", _INSTALL),
    Step("python", "pytest", "python -m pytest -q", "."),
    Setup("web", "actions/checkout@v4", (), _CHECKOUT),
    Setup("web", "pnpm/action-setup@v4", (("package_json_file", "web/package.json"),), _SETUP),
    Setup("web", "actions/setup-node@v4",
          (("cache", "pnpm"), ("cache-dependency-path", "web/pnpm-lock.yaml"), ("node-version", "22")),
          _SETUP_WARNED),
    Skip("web", "Install dependencies", "pnpm install --frozen-lockfile", _INSTALL),
    Step("web", "vitest", "pnpm test", "web"),
    Step("web", "tsc", "npx tsc --noEmit", "web"),
    Step("web", "assert-casts", "node scripts/assert-casts.mjs", "web"),
    Step("web", "assert-gates (expiry)", "node scripts/assert-gates.mjs --expiry-only", "web"),
)

STEPS: tuple[Step, ...] = tuple(e for e in MIRROR if isinstance(e, Step))

# ci.yml jobs this command does not mirror at all -> why.
CI_ONLY_JOBS: dict[str, str] = {
    "actionlint": "downloads a pinned, checksum-verified Linux binary; lints the workflows in CI only",
}


def run_steps(steps: tuple[Step, ...], execute: Callable[[Step], int]) -> list[tuple[Step, int | None]]:
    """Run each job's steps in order; a failing step ends its job, as in CI.

    Returns every step with its exit code, or None for a step its job never reached.
    """
    results: list[tuple[Step, int | None]] = []
    failed_jobs: set[str] = set()
    for step in steps:
        if step.job in failed_jobs:
            results.append((step, None))
            continue
        code = execute(step)
        results.append((step, code))
        if code != 0:
            failed_jobs.add(step.job)
    return results


def bash() -> str:
    """The bash to run steps under, or a refusal. Never cmd.exe, and never WSL's bash, which
    would run the steps against a different filesystem and toolchain."""
    path = shutil.which("bash")
    if path is None:
        raise SystemExit("ci_local: no bash on PATH. ci.yml's steps run under `bash -e`; install Git for Windows' bash.")
    if "system32" in path.lower():
        raise SystemExit(f"ci_local: the bash on PATH is WSL's ({path}). Put Git's bash first on PATH.")
    return path


def execute(step: Step, shell: str | None = None) -> int:
    print(f"\n=== {step.job} :: {step.name}   ({step.cwd}) $ {step.run}", flush=True)
    t0 = time.monotonic()
    code = subprocess.run([shell or bash(), "-e", "-c", step.run], cwd=ROOT / step.cwd).returncode
    print(f"=== {step.name}: exit {code} in {time.monotonic() - t0:.1f}s", flush=True)
    return code


def pinned(tool: str) -> str:
    """The version ci.yml pins for `node` or `python`, read off MIRROR's setup steps."""
    key = {"node": "node-version", "python": "python-version"}[tool]
    for entry in MIRROR:
        if isinstance(entry, Setup):
            for k, v in entry.inputs:
                if k == key:
                    return v
    raise KeyError(key)


def version_warning(tool: str, pin: str, local: str | None) -> str | None:
    """A warning when `local` (a `--version` line) differs from `pin` at the pin's precision."""
    found = re.search(r"\d+(?:\.\d+)*", local or "")
    if found is None:
        return f"WARNING: could not read the local {tool} version; ci.yml pins {tool} {pin}"
    parts = pin.split(".")
    have = found.group(0).split(".")[: len(parts)]
    if have == parts:
        return None
    return (
        f"WARNING: local {tool} is {found.group(0)}; ci.yml pins {tool} {pin}. "
        f"A green here is on {tool} {'.'.join(have)}, not CI's."
    )


def next_types_warning(root: Path = ROOT) -> str | None:
    """A warning when web/.next/types exists: local tsc reads it, CI's checkout has none."""
    if (root / "web" / ".next" / "types").is_dir():
        return (
            "WARNING: web/.next/types exists. web/tsconfig.json includes it, so local tsc reads "
            "this gitignored build output (global PageProps, LayoutProps) and CI's does not."
        )
    return None


def limits(shell: str) -> list[str]:
    """Where this run differs from CI's runner, as printable warnings."""
    out = []
    for tool, cmd in (("node", "node --version"), ("python", "python --version")):
        try:
            local = subprocess.run([shell, "-c", cmd], cwd=ROOT, capture_output=True, text=True).stdout
        except OSError:
            local = None
        warning = version_warning(tool, pinned(tool), local)
        if warning:
            out.append(warning)
    warning = next_types_warning()
    if warning:
        out.append(warning)
    return out


def report(results: list[tuple[Step, int | None]], warnings: list[str]) -> int:
    """Print the summary and return the exit code, which the warnings never change."""
    print("\nci_local summary (ci.yml's python and web jobs; actionlint is CI-only)")
    for step, code in results:
        verdict = "not reached" if code is None else ("ok" if code == 0 else f"FAILED (exit {code})")
        print(f"  {step.job:<7} {step.name:<24} {verdict}")
    for warning in warnings:
        print(f"  {warning}")
    ok = all(code == 0 for _, code in results)
    print("\nOK" if ok else "\nFAILED")
    return 0 if ok else 1


def main() -> int:
    shell = bash()
    warnings = limits(shell)
    for warning in warnings:
        print(warning, flush=True)
    results = run_steps(STEPS, lambda step: execute(step, shell))
    return report(results, warnings)


if __name__ == "__main__":
    sys.exit(main())

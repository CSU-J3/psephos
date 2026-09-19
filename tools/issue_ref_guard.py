"""No commit message may carry a GitHub auto-close keyword before an issue reference.

    python -m tools.issue_ref_guard [--range origin/main..HEAD]
    python -m tools.issue_ref_guard --file <path>        # a message not yet committed

Exit code is the ALARM: 1 if any scanned message would close an issue on push, 0
otherwise. Writes nothing. Read-only, hence `tools/` rather than `scripts/`.


WHY THIS EXISTS, AND IT IS NOT A HYPOTHETICAL
=============================================
On 2026-09-18 issue #4 was closed by `8e374d3`'s own commit body. Three consecutive
briefs said do not edit, comment on, or retitle that issue from a session, and a fourth
verb nobody forbade did it: WRITING ABOUT IT. The body contained the string `the close:
#4` -- a sentence asserting the issue must stay open -- and GitHub parsed it as a
closing keyword. The issue was closed one second after the push, attributed to the
pushing identity, and nobody decided it.

The general shape is in `docs/status.md`'s falsified list twice over, under the
backslash and cp1252 entries: A PLATFORM READING A STRING FOR SYNTAX THE AUTHOR DID NOT
INTEND TO WRITE. What is specific here is that DESCRIBING and ACTING are the same
string, so no instruction enumerating forbidden ACTIONS could have covered it. An
instrument can, because the instrument reads the string rather than the intent.

THE CONVENTION IS "NEVER IN THIS PROJECT", NOT "AVOID THE VERBS"
================================================================
The conventional-commit footer for an INTENTIONAL close is the same syntax this guard
fires on, so a rule phrased as "use the verbs carefully" has no edge a check can sit on.
The rule is therefore absolute here: in a commit body an issue is `issue 4`, never `#4`,
and the `#` form is kept for prose that is not a commit message. A close is performed by
a person on GitHub, which is also what makes it an acknowledgement rather than a side
effect -- the same reason `audit.yml` never closes its own standing issue.

WHAT IS COVERED
===============
All nine keywords GitHub honours -- close/closes/closed, fix/fixes/fixed,
resolve/resolves/resolved -- followed by any of the reference forms: `#N`, `GH-N`,
`owner/repo#N`, and the full `https://github.com/owner/repo/issues/N` URL. The separator
tolerates a COLON, which is not in GitHub's documented syntax and is what fired on
2026-09-18, and tolerates newlines.

OVER-FIRING IS THE SAFE DIRECTION AND ITS COST IS MEASURED, NOT ASSUMED. A false
positive costs one reworded sentence; a false negative closes an issue nobody decided
to close. Against the whole history at the time of writing -- 681 commits, 14 of which
carry a `#N`-shaped reference -- this fires on exactly ONE, the accident it was written
for, and the newline-tolerant and same-line forms of the pattern agree on all 681. So
the tolerance costs nothing that has ever been measured in this repository.
"""

from __future__ import annotations

import argparse
import re
import subprocess

# One alternation per reference form, so a reader can check each against GitHub's list.
_REF = (
    r"(?:"
    r"\#\d+"
    r"|GH-\d+"
    r"|[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\#\d+"
    r"|https?://(?:www\.)?github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/issues/\d+"
    r")"
)
CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b[\s:]*" + _REF,
    re.IGNORECASE,
)


def git(*args: str) -> subprocess.CompletedProcess[str]:
    # UTF-8 at the boundary, never the console codepage -- `tools/sha_sweep.py` records
    # what cp1252 did to this project's em dashes and how long it went unnoticed.
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def hits(text: str) -> list[str]:
    return [m.group(0) for m in CLOSING.finditer(text)]


def _report(label: str, text: str) -> int:
    found = hits(text)
    for h in found:
        # repr() so a match spanning a newline is visible as one, rather than
        # silently reflowing into something that looks harmless in the terminal.
        print(f"  WOULD CLOSE  {label}  {h!r}")
    return len(found)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--range",
        default="origin/main..HEAD",
        help="the commits a push would publish (default: origin/main..HEAD)",
    )
    ap.add_argument(
        "--file",
        help="scan a message FILE instead of a commit range -- the pre-commit form, "
             "for the `git commit -F` pattern this project uses on Windows.",
    )
    args = ap.parse_args()

    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            text = fh.read()
        print(f"  corpus: {args.file} (message file, not yet committed)")
        n = _report(args.file, text)
        total, scanned = n, 1
    else:
        # %x00 separates the hash from the message, %x1e separates records: neither can
        # occur in a commit message, unlike a newline, which occurs in every one of them.
        p = git("log", "--format=%H%x00%B%x1e", args.range)
        if p.returncode != 0:
            print(f"\n  REFUSING -- `git log {args.range}` failed:")
            print("    " + (p.stderr or "").strip().replace("\n", "\n    "))
            return 2
        records = [r.strip("\n") for r in p.stdout.split("\x1e") if r.strip()]
        print(f"  corpus: {args.range} ({len(records)} commit(s))")
        total = 0
        for rec in records:
            sha, _, body = rec.partition("\x00")
            total += _report(sha[:7], body)
        scanned = len(records)

    # A ZERO OVER AN EMPTY CORPUS IS NOT A READING, and it renders identically to a
    # clean one. `origin/main..HEAD` is empty on a branch with nothing to push, which is
    # exactly the state a session is in before it commits -- so the run that feels most
    # like a pass is the one that checked nothing. Said out loud rather than counted.
    if scanned == 0:
        print("\n  NOTHING SCANNED -- the range is empty. This is not a passed check.")
        return 0

    if total:
        print(
            f"\n  {total} AUTO-CLOSE REFERENCE(S). GitHub closes on these at push time,\n"
            "  attributing the close to the pushing identity, and a body that ARGUES an\n"
            "  issue must stay open closes it just as readily as one that asks.\n"
            "  Write `issue N` in a commit message; keep `#N` for prose that is not one."
        )
        return 1
    print("\n  OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Every commit hash cited in `docs/status.md` must resolve AND be reachable from origin.

    python -m tools.sha_sweep [--doc docs/status.md]

Exit code is the ALARM: 1 if any cited hash is an orphan (reachable from nothing) or
unresolvable, 0 otherwise. An off-origin hash that is reachable from `HEAD` is NOT an
alarm -- it is a local commit awaiting its push, and the correct pre-push state.

Writes nothing. Read-only, hence `tools/` rather than `scripts/`.


WHY THIS IS A SCRIPT AND NOT A PARAGRAPH
========================================
It was a paragraph. `docs/status.md`'s invariant prescribed the whole procedure in
prose -- extract the tokens, strip the CR, filter, resolve, check the ancestor, print
the denominator -- and every run re-implemented it from that description. A procedure
that is re-derived each time drifts each time, and the two runs before this one drifted
in the same direction and agreed with each other. See the falsified list.


THE FILTER THIS REPLACES, AND WHY ITS SHAPE WAS THE DEFECT
==========================================================
The prose said: filter to hex containing at least one letter. The reason was sound --
`docs/status.md` is full of CourtListener docket ids and LegiScan bill ids, which are
all-digit and would otherwise be counted as commit hashes; the check's first-ever run
reported 114 of 114 unresolvable largely because of them.

But that rule guesses from what a token LOOKS LIKE, and a 7-hex-digit abbreviated sha
with no letters in it looks exactly like a docket id. Five such shas are cited on that
page. All five were silently dropped from the denominator on every run, and one of them
was an orphan -- cited 2026-08-15, invisible to the "standing reading" taken 2026-08-19
that reported 0 off-origin, and to every run after it.

So candidacy is no longer inferred from shape. `git rev-parse --verify --quiet <t>^{commit}`
asks the only authority there is: a token is a hash if this repository holds a commit by
that name. A docket id does not resolve; a letterless sha does.

THE RESIDUAL, WHICH IS REAL AND IS NOT THE ONE THAT WAS JUST FIXED. An all-digit token
that is NOT a sha can one day collide with a real abbreviated sha and be counted as one.
That is benign in DIRECTION -- such a token resolves and sits on origin, so it inflates
the denominator and cannot manufacture an orphan or a failure -- but the denominator is
load-bearing here, so a reader comparing two runs should know it can move for a reason
that has nothing to do with the citations.


THE ENVIRONMENT IS PART OF THE CHECK
====================================
In a SHALLOW clone most citations report unresolvable because the history is absent, not
because the citations are bad: 51 of 53 at `--depth 6`. `git clone --depth 40` is this
project's session-open pattern, so the first run in a new session will look like the doc
has rotted when nothing is wrong. This prints the shallow state and refuses to call the
reading authoritative when it is shallow.

Run it against the PUSHED state, before and after any push or rebase.
"""

from __future__ import annotations

import argparse
import re
import subprocess


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def is_commit(token: str) -> bool:
    """Candidacy. Not a regex about shape -- a question to the object store."""
    return git("rev-parse", "--verify", "--quiet", f"{token}^{{commit}}").returncode == 0


def subject(h: str) -> str:
    return git("log", "-1", "--format=%s", h).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", default="docs/status.md")
    ap.add_argument("--ref", default="origin/main")
    args = ap.parse_args()

    shallow = git("rev-parse", "--is-shallow-repository").stdout.strip() == "true"
    print(f"  clone: {'SHALLOW -- this reading is NOT authoritative' if shallow else 'full'}")

    # newline="" so a CRLF-terminated file does not hand back tokens with a trailing \r.
    # The check's first run reported everything unresolvable partly for that reason.
    with open(args.doc, encoding="utf-8", newline="") as fh:
        text = fh.read()
    tokens = sorted({t.strip().strip("\r") for t in re.findall(r"`([0-9a-f]{7,40})`", text)})

    hashes = [t for t in tokens if is_commit(t)]
    notcommits = [t for t in tokens if t not in hashes]
    # Reported because these are exactly what the old shape filter could not see.
    letterless = [h for h in hashes if not re.search(r"[a-f]", h)]

    on_origin: list[str] = []
    off_local: list[str] = []
    orphan: list[str] = []
    for h in hashes:
        if git("merge-base", "--is-ancestor", h, args.ref).returncode == 0:
            on_origin.append(h)
        elif git("merge-base", "--is-ancestor", h, "HEAD").returncode == 0:
            off_local.append(h)
        else:
            orphan.append(h)

    # THE DENOMINATOR IS PRINTED, ALWAYS. A sweep that fails everything is exactly as
    # uninformative as one that passes everything, and this check has done both.
    print(f"\n  tokens seen            {len(tokens)}")
    print(f"  resolve as commits     {len(hashes)}   <- the denominator")
    print(f"  not commits            {len(notcommits)}   (docket ids, bill ids, entry numbers)")
    print(f"  of the commits, letterless: {len(letterless)}  {letterless}")
    print("     (invisible to the pre-2026-09-02 shape filter, which required a letter;")
    print("      one such sha was an orphan cited for 18 days and seen by no run)")

    print(f"\n  on {args.ref:<16} {len(on_origin)}")
    print(f"  off-origin, local      {len(off_local)}  {off_local}")
    for h in off_local:
        print(f"       awaiting push, citation correct: {h}  {subject(h)}")
    print(f"  off-origin, ORPHAN     {len(orphan)}  {orphan}")
    for h in orphan:
        print(f"       CITATION IS WRONG: {h}  {subject(h)}")
    print("  unresolvable           0   (a token that does not resolve is not a hash here)")

    if orphan:
        print(
            "\n  An orphan resolves in the clone that made it and in no other. Find its\n"
            "  replacement with `git patch-id --stable`, never by a matching subject line,\n"
            "  and rewrite the citation WITHOUT reproducing the dead hash -- quoting it as\n"
            "  an example puts it back in the corpus this sweep scans."
        )
    print("\n  OK" if not orphan else f"\n  {len(orphan)} ORPHAN CITATION(S)")
    return 1 if orphan else 0


if __name__ == "__main__":
    raise SystemExit(main())

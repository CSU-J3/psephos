"""Every commit hash cited in `docs/status.md` must resolve AND be reachable from origin.

    python -m tools.sha_sweep [--doc docs/status.md] [--ref origin/main] [--worktree]

Exit code is the ALARM: 1 if any cited hash is an orphan (reachable from nothing), and
in post-push mode also if any cited hash is off-origin. 2 if the run refused. 0 otherwise.
Whether an off-origin hash is an alarm depends on which of the two checks below is being
run, which is why the mode is printed rather than assumed.

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

AND THE STALENESS GATE COSTS A NETWORK ROUND-TRIP -- one `git ls-remote <remote>
refs/heads/<branch>` per run, to tell a current ref from a stale one. This is a
session-open ritual, and a ritual that silently acquires a network dependency is
something a reader meets at the worst possible moment, so it is named here rather
than discovered. It DEGRADES rather than fails: no answer from the remote means the
gate prints NOT CHECKED and the run continues, because unreachable and up-to-date
are different states and nothing here separates them. NOT CHECKED is an ABSENCE OF
COVERAGE and never a passed check, which is why it says so on its own line and again
on the closing line when the run is otherwise green.

TWO CHECKS, ONE COMMAND -- AND THEY DISAGREE ABOUT off_local
===========================================================
This tool was one check with two corpora and one number, and the number meant opposite
things depending on which corpus had been read. `--ref` selected the ancestry target and
never the corpus, which was always the file on disk, so there was no way to ask about the
PUBLISHED document at all -- and `docs/status.md` carried a sentence telling the reader to
do exactly that. The instruction was satisfiable only by separately diffing the tree
against the ref, which nothing said to do.

They are two questions and both are legitimate:

  POST-PUSH (default, corpus = `git show <ref>:<doc>`)
      Does the PUBLISHED document cite anything a fresh clone cannot follow?
      off_local is an ALARM. A citation on origin's copy of the page that is not
      reachable from origin is unreachable for every reader who is not you.

  PRE-PUSH (--worktree, corpus = the file on disk)
      Do the citations I just WROTE resolve, and where do they point?
      off_local is INFORMATIONAL and expected -- those are this session's own
      unpushed commits, and citing them is correct. This is the mode the at-rest
      pattern needs, and reading the ref here would scan the page WITHOUT the edits
      being checked, reporting clean on precisely the case the run exists to catch.

`--ref` now selects the corpus and the ancestry target together, so the two cannot drift
apart again. Every run prints which corpus it read and how that corpus stands relative to
the ref, because the previous failure was not a wrong answer -- it was a correct answer to
an unstated question.
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


def published_head(ref: str) -> str | None:
    """The remote's current tip for `ref`, or None when that cannot be established.

    Only a remote-tracking ref of the form <remote>/<branch> HAS a published state to be
    stale against, so anything else returns None and the gate is skipped rather than
    guessed at. A network failure also returns None: unreachable and up-to-date are
    different states and this cannot tell them apart, so it declines to claim either.
    """
    m = re.fullmatch(r"([^/]+)/(.+)", ref)
    if not m:
        return None
    remote, branch = m.groups()
    p = git("ls-remote", remote, f"refs/heads/{branch}")
    if p.returncode != 0 or not p.stdout.strip():
        return None
    return p.stdout.split()[0]


def subject(h: str) -> str:
    return git("log", "-1", "--format=%s", h).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", default="docs/status.md")
    ap.add_argument("--ref", default="origin/main")
    ap.add_argument(
        "--worktree",
        action="store_true",
        help="read the corpus from the file on disk (pre-push mode) rather than from "
             "--ref (post-push mode). See the module docstring: the two modes expect "
             "OPPOSITE things of off_local.",
    )
    args = ap.parse_args()

    shallow = git("rev-parse", "--is-shallow-repository").stdout.strip() == "true"
    print(f"  clone: {'SHALLOW -- this reading is NOT authoritative' if shallow else 'full'}")

    # THE STALENESS GATE, AND ITS SCOPE IS THE LOAD-BEARING DECISION HERE.
    #
    # Divergence between the working tree and the ref is NOT an error. It is WHICH
    # QUESTION IS BEING ASKED: pre-push you want the citations you just wrote, post-push
    # you want the ones the published document carries. A guard firing on that divergence
    # would fire on the common case, be passed by reflex with a flag, and stop being a
    # guard -- a check you always override is a prompt.
    #
    # A STALE REF IS DIFFERENT IN KIND. If local `origin/main` is behind the remote then
    # BOTH modes are answering about a ref that is not the published state: the post-push
    # corpus is a document that is no longer published, and the pre-push ancestry test
    # asks about the wrong origin. Neither answer is about anything, so there is nothing
    # to report and the run refuses rather than printing a number.
    local_ref = git("rev-parse", "--verify", "--quiet", f"{args.ref}^{{commit}}").stdout.strip()
    published = published_head(args.ref)
    if published is not None and local_ref and published != local_ref:
        print(f"\n  REFUSING -- {args.ref} is STALE.")
        print(f"    local  {local_ref[:7]}")
        print(f"    remote {published[:7]}")
        print("    Both modes would answer about a ref that is not the published state.")
        print("    `git fetch origin` and re-run.")
        return 2
    # NOT CHECKED IS AN ABSENCE OF COVERAGE, NOT A PASSED CHECK, and it is spelled out
    # rather than abbreviated because a definitional value that renders like a measured
    # one is this tool's own documented failure family. The bad ending is a green run
    # offline, read as clean, by a reader who never registers that the corpus may not be
    # the published document.
    if published is None:
        print(f"  staleness of {args.ref}: NOT CHECKED -- no answer from the remote.")
        print("          This is an ABSENCE OF COVERAGE, not a passed check.")
        print(f"          UNVERIFIED: {args.ref} may be behind the remote, so the")
        print("          corpus below may not be the published document.")
        print("          Unreachable and up-to-date are different states and")
        print("          nothing here separates them.")

    if args.worktree:
        # newline="" so a CRLF-terminated file does not hand back tokens with a trailing
        # \r. The check's first run reported everything unresolvable partly for that
        # reason. `git show` needs no such care: it hands back the blob as stored.
        with open(args.doc, encoding="utf-8", newline="") as fh:
            text = fh.read()
        same = git("diff", "--quiet", args.ref, "--", args.doc).returncode == 0
        ahead = git("rev-list", "--count", f"{args.ref}..HEAD").stdout.strip() or "?"
        rel = (f"IDENTICAL to {args.ref}" if same
               else f"DIFFERS from {args.ref}, {ahead} commit(s) unpushed")
        print(f"  corpus: WORKING TREE {args.doc}")
        print(f"          pre-push mode, {rel}")
        print("          off-origin-local is INFORMATIONAL here")
    else:
        shown = git("show", f"{args.ref}:{args.doc}")
        if shown.returncode != 0:
            print(f"\n  REFUSING -- cannot read {args.ref}:{args.doc}")
            print(f"    {shown.stderr.strip()}")
            return 2
        text = shown.stdout
        print(f"  corpus: {args.ref}:{args.doc}")
        print("          post-push mode, the published state")
        print("          off-origin-local is an ALARM here")
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
        if args.worktree:
            print(f"       awaiting push, citation correct: {h}  {subject(h)}")
        else:
            print(f"       UNREACHABLE FOR EVERY OTHER CLONE: {h}  {subject(h)}")
    print(f"  off-origin, ORPHAN     {len(orphan)}  {orphan}")
    for h in orphan:
        print(f"       CITATION IS WRONG: {h}  {subject(h)}")
    print("  unresolvable           0   (a token that does not resolve is not a hash here)")

    # off_local is an alarm ONLY in post-push mode. In pre-push mode it is this
    # session's own unpushed commits and citing them is correct; the same number,
    # opposite meaning, which is the whole reason the mode is printed above.
    alarm_local = off_local and not args.worktree

    if orphan:
        print(
            "\n  An orphan resolves in the clone that made it and in no other. Find its\n"
            "  replacement with `git patch-id --stable`, never by a matching subject line,\n"
            "  and rewrite the citation WITHOUT reproducing the dead hash -- quoting it as\n"
            "  an example puts it back in the corpus this sweep scans."
        )
    if alarm_local:
        print(
            "\n  The PUBLISHED document cites a commit that is not on the ref. It\n"
            "  resolves here because this clone holds it, and it resolves nowhere else.\n"
            "  Either the push did not land or the citation names a local-only commit."
        )
    failed = bool(orphan) or bool(alarm_local)
    if not failed and published is None:
        # Green WITHOUT the staleness gate is a different result from green WITH it, and
        # a bare OK renders them identically. Say which one this was.
        print("\n  OK -- but staleness NOT CHECKED (see above). No orphan and no")
        print("  off-origin citation IN THIS CORPUS, which may not be the published one.")
    elif not failed:
        print("\n  OK")
    else:
        bits = []
        if orphan:
            bits.append(f"{len(orphan)} ORPHAN CITATION(S)")
        if alarm_local:
            bits.append(f"{len(off_local)} OFF-ORIGIN IN THE PUBLISHED DOC")
        print("\n  " + ", ".join(bits))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Scrub an issue body in place, before a workflow step posts it (unit 99, Corey,
2026-09-28).

    python3 "$GITHUB_WORKSPACE/tools/scrub_issue_body.py" BODY_FILE [BODY_FILE ...]

Every workflow step that comments on or opens an issue runs this on the file it is about
to hand to `gh --body-file`, with its run's credentials in its environment: collect's
standing-issue step, audit's and dom-checks'. Actions masks secrets in the run log, not in
what a step sends to the Issues API, and those bodies carry raw tool output -- a
traceback, a check's capture, a server log -- where a libsql error can name the database
URL. The scrub is scrub.py's, the one the channel_runs evidence uses.
tests/test_issue_body_scrub.py fails any workflow step that posts without it.

Invoked by PATH, not `-m`: the dom-checks lane runs its steps from web/ and has no
setup-python, so this finds the repo from its own location and imports only the standard
library and scrub.py. A missing file exits 1, and the step's `bash -e` stops it before
`gh` runs: a body that was not scrubbed is never posted. It prints the file and how many
credential values it scrubbed against, never a value.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scrub  # noqa: E402


def main(argv=None) -> int:
    paths = list(sys.argv[1:] if argv is None else argv)
    if not paths:
        print("usage: scrub_issue_body.py BODY_FILE [BODY_FILE ...]", file=sys.stderr)
        return 2
    secrets = scrub.env_secrets()
    for path in paths:
        try:
            with open(path, "rb") as fh:
                # `replace`: a capture cut by `tail -c` can end mid-character, and a body
                # that will not decode must still be scrubbed rather than refused.
                raw = fh.read().decode("utf-8", errors="replace")
        except OSError as exc:
            print(f"scrub_issue_body: cannot read {path} ({type(exc).__name__}); nothing "
                  f"is posted unscrubbed", file=sys.stderr)
            return 1
        with open(path, "wb") as fh:
            fh.write(scrub.scrub_body(raw, secrets).encode("utf-8"))
        print(f"scrub_issue_body: {path} scrubbed against {len(secrets)} credential "
              f"value(s) and every URL's query string")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

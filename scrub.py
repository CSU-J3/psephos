"""The one scrub for anything this project sends outside the run log (unit 99, Corey,
2026-09-28).

Actions masks registered secrets in the run LOG. It does not mask text a step sends to
the Issues API, so every issue body every lane posts passes through here first: collect's
Verdict comment, the coverage_audit issue and the dom-checks issue, each by
tools/scrub_issue_body.py on the file it is about to hand to `gh --body-file`
(tests/test_issue_body_scrub.py fails any workflow step that posts without it). The
channel_runs evidence uses the same primitives, through run_signals.

STANDARD LIBRARY ONLY, and that is load-bearing: the dom-checks lane has no setup-python
and no project dependencies, and runs this on the runner's own python3.

What it does, in this order:
  1. drops every URL's query string and fragment -- the key rides there on Congress.gov
     (`api_key=`) and LegiScan (`key=`), and the Turso token on `libsql://...?authToken=`.
     First, because a redacted URL is no longer a URL for the query rule to find (the
     planted-value test caught the other order leaving `?authToken=` behind);
  2. replaces every credential the run carries (CREDENTIAL_ENV, read from the step's
     environment), longest first, plus the Turso URL's bare host, which a libsql error
     can name on its own;
  3. nothing else: no truncation and no whitespace folding, so a body keeps its layout.
Values are compared with str.replace in memory. Nothing here prints one or puts one on
a command line (the secret-audit rule).
"""
from __future__ import annotations

import os
import re

REDACTED = "[redacted]"
# A value shorter than this is never treated as a secret: real keys run 32 to 40
# characters, and scrubbing a short one would redact ordinary text -- a test's key "k"
# turned every "skipped" in later output into "s[redacted]ipped" before this guard.
MIN_SECRET_LEN = 8

# Every credential a run can carry, by variable name. A step's scrub knows the values its
# own environment holds; each posting step is given its run's credentials for that reason
# (tests/test_issue_body_scrub.py checks the env). Pinned against config/sources.yaml's
# key_env names by tests/test_unit99_secrets.py.
CREDENTIAL_ENV = ("CONGRESS_API_KEY", "COURTLISTENER_TOKEN", "LEGISCAN_API_KEY",
                  "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN")

_URL_QUERY = re.compile(r"(\b[A-Za-z][A-Za-z0-9+.-]*://[^\s?#\"'<>]*)[?#][^\s\"'<>]*")


def env_secrets() -> tuple[str, ...]:
    """Every credential value in this process's environment, plus the database URL's bare
    host, which a libsql error can name on its own."""
    out = []
    for name in CREDENTIAL_ENV:
        v = (os.environ.get(name) or "").strip()
        if not v:
            continue
        out.append(v)
        if name == "TURSO_DATABASE_URL":
            out.append(v.split("://", 1)[-1].split("/", 1)[0].split("?", 1)[0])
    return tuple(s for s in dict.fromkeys(out) if len(s) >= MIN_SECRET_LEN)


def strip_queries(text: str) -> str:
    """`text` with every URL's query string and fragment removed; the rest of the URL
    stays, so a reader still sees which endpoint answered."""
    return _URL_QUERY.sub(r"\1", text)


def replace_all(text: str, secrets) -> str:
    """Every secret of at least MIN_SECRET_LEN replaced, longest first: the Turso URL
    contains its host, and replacing the host first would leave the URL's scheme and path
    around a redaction instead of one clean mark."""
    for s in sorted({s for s in secrets if s and len(s) >= MIN_SECRET_LEN}, key=len,
                    reverse=True):
        text = text.replace(s, REDACTED)
    return text


def scrub_body(text, secrets=None) -> str:
    """The scrub: queries stripped, then every credential replaced; layout untouched.
    `secrets` defaults to this process's environment (env_secrets)."""
    return replace_all(strip_queries(str(text)),
                       env_secrets() if secrets is None else secrets)

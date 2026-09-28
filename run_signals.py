"""A collect run's loud lines, and the per-run rows that carry them to Turso (unit 99).

WHY THIS EXISTS. The Congress.gov key sat disabled for 33 scheduled runs and every one
concluded `success`: legislation printed six `ERROR:` lines a run and exited 0, the
exit-0 invariant working exactly as designed, and nothing downstream read a log. Unit 99's
rulings (Corey, 2026-09-28) keep the invariant -- a collector still exits 0 -- and make
the failure LOUD instead: a literal line in the log, and a row in `channel_runs` that the
collect run's final step (`tools/collect_verdict.py`) reads to turn the run red and
comment on the standing issue.

THE CLASSES, and which are loud:

    credential failure  LOUD  the source refused the key (R2, R3)
    missing secret      LOUD  the key's variable is empty; the channel skipped (R5)
    no OK replies       LOUD  state reached LegiScan and got no OK reply at all (R3)
    cut short           LOUD  work owed this run was left undone with nothing
                              guaranteeing the next run picks it up (R6)
    deferred            quiet planned deferral -- proration, the walk budget, the
                              refresh rotation -- printed, never loud (R6)
    ok                  quiet the channel reached its source; state's receipt (R7, R9)
    unreached           quiet the channel ran to its end, met none of the above and got
                              no OK reply -- every request failed some other way (a 5xx
                              run, a transport outage). Its receipt governs it (R9); the
                              row says the collector ENDED, which no row cannot say

THE LINE NAMES THE CHANNEL AND NOTHING ABOUT THE KEY. It is a literal prefix and the
channel; an evidence suffix may follow, but every evidence string passes `scrub()`, which
removes the channel's own secret values wherever they occur and truncates. A quoted
response body is therefore safe to print even if a server were to echo the key. Nothing
here formats an exception's `__cause__` or a URL with its query string: a
`RetriesExhausted` chains urllib3's error, whose text can carry `?api_key=`.
"""
from __future__ import annotations

import os
import re
import sys

import common
import config
import db

OK = "ok"
CREDENTIAL = "credential failure"
MISSING = "missing secret"
NO_OK = "no OK replies"
CUT = "cut short"
DEFERRED = "deferred"
UNREACHED = "unreached"
CLASSES = (OK, CREDENTIAL, MISSING, NO_OK, CUT, DEFERRED, UNREACHED)
LOUD = frozenset({CREDENTIAL, MISSING, NO_OK, CUT})

# The printed prefix per class. A missing secret prints the credential line (R5: "that
# channel prints its line"), and its row carries the distinct class.
PREFIX = {
    CREDENTIAL: "CREDENTIAL FAILURE",
    MISSING: "CREDENTIAL FAILURE",
    NO_OK: "NO OK REPLIES",
    CUT: "RUN CUT SHORT",
    DEFERRED: "DEFERRED",
}

TABLE = "channel_runs"
EVIDENCE_MAX = 300
REDACTED = "[redacted]"

# Every secret any channel in this process has handed to RunSignals. `safe()` scrubs them
# from lines printed OUTSIDE this module -- the per-item ERROR and skip lines that predate
# unit 99 and print an exception's text, which carries the response body: a server that
# echoed the key would otherwise put it in the public log (found by unit 99's tests).
_SECRETS: set[str] = set()
# A value shorter than this is never treated as a secret: real keys run 32 to 40
# characters, and scrubbing a short one would redact ordinary text -- a test's key "k"
# turned every "skipped" in later output into "s[redacted]ipped" before this guard.
MIN_SECRET_LEN = 8


# Every credential a collect run carries, by variable name (unit 99, ruling 2a). The
# collectors step hands all five to every collector process, so each channel scrubs every
# one, not only its own key: an error from one source that echoed another's key, or a
# database error naming the Turso URL, still stays out of the evidence, the issue comment
# and the log. Pinned against config/sources.yaml's key_env names by a test.
CREDENTIAL_ENV = ("CONGRESS_API_KEY", "COURTLISTENER_TOKEN", "LEGISCAN_API_KEY",
                  "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN")

# A URL's query string -- and fragment -- is dropped from evidence whatever it carries
# (ruling 2a): the key rides there on Congress.gov (`api_key=`) and LegiScan (`key=`), and
# a server that echoes the request URL would put it into a body the evidence quotes.
_URL_QUERY = re.compile(r"(\b[A-Za-z][A-Za-z0-9+.-]*://[^\s?#\"'<>]*)[?#][^\s\"'<>]*")


def env_secrets() -> tuple[str, ...]:
    """Every credential value in this process's environment, plus the database URL's bare
    host, which a libsql error can name on its own. Held in memory and compared by
    str.replace only: nothing here prints a value or puts one on a command line."""
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
    stays, so the evidence still says which endpoint answered."""
    return _URL_QUERY.sub(r"\1", text)


def _replace_all(text: str, secrets) -> str:
    # Longest first: the Turso URL contains its host, and replacing the host first would
    # leave the URL's scheme and path around a redaction instead of one clean mark.
    for s in sorted({s for s in secrets if s and len(s) >= MIN_SECRET_LEN}, key=len,
                    reverse=True):
        text = text.replace(s, REDACTED)
    return text


def safe(text) -> str:
    """`text` with every registered secret replaced, and nothing else changed -- no
    truncation, no whitespace folding -- so an existing line keeps its shape."""
    return _replace_all(str(text), _SECRETS)


def run_id() -> str:
    """GitHub's run id inside Actions, `local` elsewhere; from a re-run's second attempt
    on, the attempt too. A re-run reuses the run id, and the rows are keyed per class, so
    without the attempt a clean second attempt would still find the first one's loud
    rows and read red. The collectors and the verdict both read it from here."""
    rid = os.environ.get("GITHUB_RUN_ID") or "local"
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT") or "1"
    return rid if attempt == "1" else f"{rid}.{attempt}"


def secret(name: str) -> str:
    """The named secret's value, or '' when it is empty or unset. Goes through
    `config.require_env`, so there is one definition of "missing", and catches its
    SystemExit: under R5 a missing secret skips its channel instead of ending the step."""
    try:
        return config.require_env(name)
    except SystemExit:
        return ""


def scrub(text: str, secrets=()) -> str:
    """Evidence fit to print: every URL's query string dropped, every non-empty secret
    value replaced, whitespace collapsed, truncated -- in that order. Queries first,
    because a redacted URL is no longer a URL: replacing the Turso URL first left its
    `?authToken=` behind for the query rule to miss (the ruling-2a test found it).
    Truncation last, so it can leave no key's prefix behind. Replacement, not a check: a
    Python str.replace puts no value on any command line, which is the secret-audit rule's
    reason for doing it in-process."""
    out = _replace_all(strip_queries(str(text or "")), secrets)
    out = re.sub(r"\s+", " ", out).strip()
    if len(out) > EVIDENCE_MAX:
        out = out[: EVIDENCE_MAX - 3] + "..."
    return out


def quote(text: str, secrets=()) -> str:
    """A response body or alert, scrubbed and in double quotes."""
    return '"' + scrub(text, secrets).replace('"', "'") + '"'


class RunSignals:
    """One channel's account of this run: the loud and deferred classes it met, each
    printed once, and whether it reached its source at all.

    `note()` prints the class's line the FIRST time that class is met and keeps that
    first evidence; later notes of the same class only count. `reached()` counts replies
    the source answered OK. `flush()` writes one `channel_runs` row per class met, plus an
    `ok` row when the channel reached its source -- that `ok` row is state's receipt --
    and an `unreached` row when it did neither, so every run that ends leaves a row."""

    def __init__(self, channel: str, secrets=()):
        self.channel = channel
        # The channel's own key, and every credential the run carries (CREDENTIAL_ENV).
        self.secrets = tuple(dict.fromkeys(s for s in (*secrets, *env_secrets()) if s))
        _SECRETS.update(s for s in self.secrets if len(s) >= MIN_SECRET_LEN)
        self.notes: dict[str, str] = {}
        self.counts: dict[str, int] = {}
        self.ok_replies = 0
        self._deferred: list[str] = []

    def note(self, cls: str, evidence: str = "") -> None:
        """A LOUD class prints its line once, on its first evidence. A planned deferral
        prints EVERY distinct evidence once (R6: every planned deferral prints a line --
        a capped refresh must not vanish behind a walk deferral noted first), and its row
        carries them all."""
        if cls not in PREFIX:
            raise ValueError(f"not a noted class: {cls!r}")
        self.counts[cls] = self.counts.get(cls, 0) + 1
        ev = scrub(evidence, self.secrets)
        if cls == DEFERRED:
            if ev in self._deferred:
                return
            self._deferred.append(ev)
            self.notes[cls] = scrub("; ".join(self._deferred))
        else:
            if cls in self.notes:
                return
            self.notes[cls] = ev
        line = f"{PREFIX[cls]} {self.channel}" + (f": {ev}" if ev else "")
        print(line, flush=True)

    def reached(self, n: int = 1) -> None:
        self.ok_replies += n

    def has(self, cls: str) -> bool:
        return cls in self.notes

    def loud(self) -> bool:
        return any(c in LOUD for c in self.notes)

    def rows(self) -> list[dict]:
        stamp = common.now_iso()
        rid = run_id()
        out = [{"run_id": rid, "channel": self.channel, "class": cls,
                "evidence": ev, "written_at": stamp} for cls, ev in self.notes.items()]
        if self.ok_replies:
            out.append({"run_id": rid, "channel": self.channel, "class": OK,
                        "evidence": f"{self.ok_replies} OK repl{'y' if self.ok_replies == 1 else 'ies'}",
                        "written_at": stamp})
        if not out:
            # R7: every run writes its row. Without this, a channel whose every request
            # failed quietly wrote nothing, and the verdict read it as a collector that
            # died ("unrecorded") -- red at once, where R9 hands that case to the receipt.
            out.append({"run_id": rid, "channel": self.channel, "class": UNREACHED,
                        "evidence": "no request answered OK and no loud class met; "
                                    "the receipt governs (R9)",
                        "written_at": stamp})
        return out

    def flush(self, conn) -> bool:
        """Write this run's rows and commit. Guarded, like every per-item write: a
        failure here prints and returns False rather than raising, so the collector keeps
        its exit 0. The printed line has already reached the log either way, and the
        verdict step reads a missing row as a failure of its own (see collect_verdict)."""
        rows = self.rows()
        try:
            for row in rows:
                db.upsert(conn, TABLE, row, "run_id, channel, class")
            conn.commit()
            return True
        except Exception as exc:
            # recover() itself can raise on the remote (its reopen runs the retry ladder),
            # and flush() runs at the end of EVERY run now: a raise here would turn a
            # clean run's last write into a non-zero exit that ends the `bash -e` step.
            try:
                db.recover(conn)
            except Exception:
                pass
            print(f"  {self.channel}: channel_runs write failed; the verdict step will read "
                  f"this run as unrecorded -- {scrub(str(exc), self.secrets)}", file=sys.stderr)
            return False

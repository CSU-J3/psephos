"""What the scheduled lanes did since the last session: every collect, audit and dom-checks
run with its conclusion, and every new comment on the standing issues, the reds first
(Corey, 2026-10-05). The session-open ritual's one command (CLAUDE.md, docs/status.md):
run it before anything else and report what it prints first.

Why it exists: the 2026-10-04 06:17Z slot's collect run (37201585654) went red at 12:23Z
and commented on "collect red", and no session read it until Corey's screenshot the next
day. The session open then listed collect runs only to gate its pushes, with --limit 1 to
3, and the red was never in view.

    python -m tools.lanes_since [--since ISO-8601]

--since defaults to the newest commit on origin/main that is not the cron's `data:` commit:
the last session's own push (run `git fetch` first). Read-only; needs `gh`, signed in.
Exits 1 when any run since is not green or a standing issue has a new comment, so the
reading cannot pass for quiet.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone

WORKFLOWS = ("collect.yml", "audit.yml", "dom-checks.yml")
STANDING = ("collect red", "recheck flags")


def _run(args: list[str]) -> str:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", check=True).stdout


def gh_json(args: list[str]):
    return json.loads(_run(["gh", *args]) or "null")


def when(stamp: str) -> datetime:
    """An ISO 8601 stamp as an instant, compared as one whatever zone it was written in;
    a stamp with no zone is read as UTC."""
    t = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def default_since(run=_run) -> str:
    """The newest commit on origin/main that the cron did not write."""
    return run(["git", "log", "origin/main", "--invert-grep", "--grep=^data:", "-1", "--format=%cI"]).strip()


def runs_since(since: datetime, gh=gh_json) -> list[dict]:
    out = []
    for wf in WORKFLOWS:
        rows = gh(["run", "list", "--workflow", wf, "--limit", "100", "--json",
                   "databaseId,status,conclusion,createdAt,event,displayTitle"]) or []
        out += [{**r, "workflow": wf} for r in rows if when(r["createdAt"]) >= since]
    return sorted(out, key=lambda r: when(r["createdAt"]))


def comments_since(since: datetime, gh=gh_json) -> list[dict]:
    issues = gh(["issue", "list", "--state", "all", "--limit", "200", "--json", "number,title,state"]) or []
    out = []
    for issue in issues:
        if issue["title"] not in STANDING:
            continue
        comments = (gh(["issue", "view", str(issue["number"]), "--json", "comments"]) or {}).get("comments") or []
        out += [{"issue": issue["number"], "title": issue["title"], "state": issue["state"], **c}
                for c in comments if when(c["createdAt"]) >= since]
    return sorted(out, key=lambda c: when(c["createdAt"]))


def green(r: dict) -> bool:
    return r.get("status") == "completed" and r.get("conclusion") == "success"


def report(since: str, runs: list[dict], comments: list[dict]) -> tuple[str, int]:
    """The reading, the reds first, and its exit code."""
    red = [r for r in runs if r.get("status") == "completed" and not green(r)]
    open_ = [r for r in runs if r.get("status") != "completed"]
    lines = [f"lanes since {since}: {len(runs)} run(s), {len(red)} not green, {len(open_)} still running; "
             f"{len(comments)} new comment(s) on the standing issues"]
    for r in red:
        lines.append(f"  RED   {r['createdAt']}  {r['workflow']:15} {r['conclusion']:9} run {r['databaseId']}  {r['displayTitle']}")
    for c in comments:
        first = (c.get("body") or "").strip().splitlines()
        lines.append(f"  NEW   {c['createdAt']}  #{c['issue']} {c['title']} ({c['state'].lower()}), "
                     f"{(c.get('author') or {}).get('login', '?')}: {first[0][:120] if first else ''}")
    for r in runs:
        mark = "ok   " if green(r) else ("run  " if r.get("status") != "completed" else "red  ")
        lines.append(f"  {mark} {r['createdAt']}  {r['workflow']:15} {r.get('conclusion') or r.get('status'):9} "
                     f"run {r['databaseId']}  {r['displayTitle']}")
    return "\n".join(lines), (1 if red or comments else 0)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    since = argv[argv.index("--since") + 1] if "--since" in argv else default_since()
    text, code = report(since, runs_since(when(since)), comments_since(when(since)))
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

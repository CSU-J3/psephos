"""tools/lanes_since.py: the session-open reading of the scheduled lanes (Corey, 2026-10-05).

`gh` is faked: each case hands the tool the JSON `gh run list`, `gh issue list` and
`gh issue view` would return, the 2026-10-04 06:17Z red among them."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools import lanes_since as L  # noqa: E402

RUNS = {
    "collect.yml": [
        {"databaseId": 37218252141, "status": "completed", "conclusion": "success", "createdAt": "2026-10-04T16:50:30Z",
         "event": "schedule", "displayTitle": "collect 17 12 * * *"},
        {"databaseId": 37201585654, "status": "completed", "conclusion": "failure", "createdAt": "2026-10-04T12:17:20Z",
         "event": "schedule", "displayTitle": "collect 17 6 * * *"},
        {"databaseId": 37154215895, "status": "completed", "conclusion": "success", "createdAt": "2026-10-03T21:11:14Z",
         "event": "schedule", "displayTitle": "collect 17 18 * * *"},
    ],
    "audit.yml": [
        {"databaseId": 1, "status": "in_progress", "conclusion": "", "createdAt": "2026-10-05T12:20:20Z",
         "event": "schedule", "displayTitle": "audit"},
    ],
    "dom-checks.yml": [],
}
ISSUES = [{"number": 6, "title": "collect red", "state": "OPEN"},
          {"number": 9, "title": "recheck flags", "state": "OPEN"},
          {"number": 1, "title": "coverage audit failed", "state": "OPEN"}]
COMMENTS = {
    6: [{"createdAt": "2026-10-04T12:23:31Z", "author": {"login": "github-actions"}, "body": "cc @CSU-J3\n\n**collect red**"},
        {"createdAt": "2026-09-30T20:08:43Z", "author": {"login": "CSU-J3"}, "body": "older"}],
    9: [],
    1: [{"createdAt": "2026-10-04T13:00:00Z", "author": {"login": "github-actions"}, "body": "not a standing issue here"}],
}


def fake_gh(runs=RUNS, issues=ISSUES, comments=COMMENTS):
    def gh(args):
        if args[:2] == ["run", "list"]:
            return runs[args[args.index("--workflow") + 1]]
        if args[:2] == ["issue", "list"]:
            return issues
        if args[:2] == ["issue", "view"]:
            return {"comments": comments[int(args[2])]}
        raise AssertionError(args)
    return gh


# The last session's push, as git prints it in Mountain time: 02:25:15Z on 10-04.
SINCE = "2026-10-03T20:25:15-06:00"


def test_since_is_read_in_its_own_zone():
    assert L.when(SINCE) == datetime(2026, 10, 4, 2, 25, 15, tzinfo=timezone.utc)
    assert L.when("2026-10-04T12:17:20Z") == datetime(2026, 10, 4, 12, 17, 20, tzinfo=timezone.utc)
    assert L.when("2026-10-04T12:17:20") == datetime(2026, 10, 4, 12, 17, 20, tzinfo=timezone.utc)   # no zone: UTC


def test_every_lane_run_since_is_listed_in_order_and_none_before():
    runs = L.runs_since(L.when(SINCE), fake_gh())
    assert [r["databaseId"] for r in runs] == [37201585654, 37218252141, 1]
    assert [r["workflow"] for r in runs] == ["collect.yml", "collect.yml", "audit.yml"]


def test_only_the_standing_issues_new_comments_are_read():
    comments = L.comments_since(L.when(SINCE), fake_gh())
    assert [(c["issue"], c["createdAt"]) for c in comments] == [(6, "2026-10-04T12:23:31Z")]


def test_the_report_puts_the_red_and_the_new_comment_first_and_exits_1():
    gh = fake_gh()
    text, code = L.report(SINCE, L.runs_since(L.when(SINCE), gh), L.comments_since(L.when(SINCE), gh))
    lines = text.splitlines()
    assert code == 1
    assert lines[0].startswith(f"lanes since {SINCE}: 3 run(s), 1 not green, 1 still running; 1 new comment(s)")
    assert lines[1].startswith("  RED   2026-10-04T12:17:20Z  collect.yml") and "run 37201585654" in lines[1]
    assert lines[2].startswith("  NEW   2026-10-04T12:23:31Z  #6 collect red (open), github-actions: cc @CSU-J3")
    # A run still going is listed, never counted red.
    assert any(ln.startswith("  run   2026-10-05T12:20:20Z  audit.yml") for ln in lines)


def test_a_new_comment_alone_exits_1():
    green_only = {**RUNS, "collect.yml": [RUNS["collect.yml"][0]], "audit.yml": []}
    gh = fake_gh(runs=green_only)
    text, code = L.report(SINCE, L.runs_since(L.when(SINCE), gh), L.comments_since(L.when(SINCE), gh))
    assert code == 1 and "0 not green" in text.splitlines()[0]


def test_a_quiet_window_exits_0():
    quiet = {**RUNS, "collect.yml": [RUNS["collect.yml"][0]], "audit.yml": []}
    gh = fake_gh(runs=quiet, comments={6: [], 9: [], 1: []})
    text, code = L.report(SINCE, L.runs_since(L.when(SINCE), gh), L.comments_since(L.when(SINCE), gh))
    assert code == 0 and text.splitlines()[0].endswith("0 new comment(s) on the standing issues")


def test_the_default_since_is_the_newest_commit_the_cron_did_not_write():
    seen = []

    def run(args):
        seen.append(args)
        return "2026-10-04T20:24:35-06:00\n"
    assert L.default_since(run) == "2026-10-04T20:24:35-06:00"
    assert seen == [["git", "log", "origin/main", "--invert-grep", "--grep=^data:", "-1", "--format=%cI"]]

"""tools/reader_launch.py: readers start blind from the stored launcher, and a run fails when
one did not (Corey's rulings, 2026-10-03, ruling 1)."""
import json
import re

import pytest

from tools import reader_launch as RL

PAIR = {"n": 1, "pair": {"rows": [91090, 91356], "objects": [479082481, 479305491],
                         "case_id": "73582123"}}
NOTE = RL.HANDBACK_NOTE + ": when your work is complete, call SubagentHandback.\n</system-reminder>"
GOOD = json.dumps({"verdicts": [{"n": 1, "same_entry": "yes", "better_match": None, "reasoning": "r"}]})


def _staged(tmp_path, records=(PAIR,)):
    return RL.stage(list(records), str(tmp_path / "blind"))


def _lines(file, start, *, before=(), after=(), attachments=("environment", "date"),
           tools=None, report=GOOD, began="2026-10-03T03:00:00.000Z"):
    """A transcript in the shape the Agent-tool channel writes: the start message, its
    context attachments, the hand-back note, a Read of the file and the report."""
    lines = [{"type": "user", "timestamp": began, "message": {"role": "user", "content": m}} for m in before]
    lines.append({"type": "user", "timestamp": began, "message": {"role": "user", "content": start}})
    lines += [{"type": "attachment", "attachment": {"type": a}} for a in attachments]
    lines.append({"type": "user", "message": {"role": "user", "content": NOTE}})
    lines += [{"type": "user", "message": {"role": "user", "content": m}} for m in after]
    for i, (name, inp) in enumerate(tools or [("Read", {"file_path": file})]):
        lines.append({"type": "assistant", "requestId": f"q{i}", "message": {
            "content": [{"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}],
            "usage": {"input_tokens": 10, "cache_creation_input_tokens": 100,
                      "cache_read_input_tokens": 1000, "output_tokens": 5}}})
        lines.append({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": open(file, encoding="utf-8").read()
             if name == "Read" else "ok"}]}})
    lines.append({"type": "assistant", "requestId": "qh", "message": {
        "content": [{"type": "tool_use", "id": "th", "name": "SubagentHandback", "input": {"message": report}}],
        "usage": {"input_tokens": 1, "cache_creation_input_tokens": 0,
                  "cache_read_input_tokens": 2000, "output_tokens": 50}}})
    return lines


# --------------------------------------------------------------------------- #
# The launcher
# --------------------------------------------------------------------------- #
def test_the_launcher_names_only_the_lens_and_the_file(tmp_path):
    f = _staged(tmp_path)
    msgs = {lens: RL.render(lens, f) for lens in RL.LENSES}
    ln = RL.launcher()
    for lens, msg in msgs.items():
        assert msg.endswith(f"Your lens: {lens}\nYour file: {f}")
        assert ln["lenses"][lens] in msg and "{{" not in msg
        rest = msg.replace(ln["lenses"][lens], "").replace(f"Your lens: {lens}", "").replace(f, "")
        assert rest == msgs["identity"].replace(ln["lenses"]["identity"], "").replace(
            "Your lens: identity", "").replace(f, "")          # the rest is one fixed text


@pytest.mark.parametrize("lens", RL.LENSES)
def test_the_launcher_carries_no_ruling_finding_pair_number_or_outcome(tmp_path, lens):
    msg = RL.render(lens, _staged(tmp_path))
    msg = msg.replace(msg.split("Your file: ")[1], "")         # the opaque path
    for pat in (r"\bCorey\b", r"\brul(ing|ed)s?\b", r"\brefused\b", r"strict-B", r"\bR1\b",
                r"\b\d{5,}\b", r"[Pp]air \d", r"\bn=\d", r"\bsplits?\b", r"\bduplicate\b",
                r"gates\.yaml", r"\bfinding", r"\b(is|was|been|now) linked\b", r"\bcandidate"):
        assert not re.search(pat, msg), pat


def test_render_refuses_a_file_whose_name_could_carry_a_label(tmp_path):
    named = tmp_path / "ctl_p6.json"
    named.write_text(json.dumps([PAIR]), encoding="utf-8")
    with pytest.raises(ValueError):
        RL.render("identity", str(named))
    f = _staged(tmp_path)
    RL.render("identity", f)
    with open(f, "a", encoding="utf-8") as h:                   # changed since it was staged
        h.write(" ")
    with pytest.raises(ValueError):
        RL.render("identity", f)


# --------------------------------------------------------------------------- #
# The check
# --------------------------------------------------------------------------- #
def test_a_reader_that_began_from_the_launcher_passes(tmp_path):
    f = _staged(tmp_path)
    c = RL.check_transcript(_lines(f, RL.render("clocks", f)), "clocks", f)
    assert c["ok"], c["problems"]
    assert c["reads_of_file"] == 1 and c["verdicts"][0]["same_entry"] == "yes"


def test_a_relayed_brief_ahead_of_the_launcher_fails_the_reader(tmp_path):
    f = _staged(tmp_path)
    relay = "[Workflow harness - user request] ... Pair 22's finding (rows 91090/91356) ..."
    c = RL.check_transcript(_lines(f, RL.render("clocks", f), before=[relay]), "clocks", f)
    assert not c["ok"]
    assert any("not the launcher" in p for p in c["problems"])
    assert any("pair ids outside its file" in p for p in c["problems"])


def test_any_message_but_the_hand_back_note_fails_the_reader(tmp_path):
    f = _staged(tmp_path)
    c = RL.check_transcript(_lines(f, RL.render("identity", f), after=["the 6 splits"]), "identity", f)
    assert not c["ok"] and any("other than the hand-back note" in p for p in c["problems"])


def test_an_attachment_of_an_unmeasured_type_fails_the_reader(tmp_path):
    f = _staged(tmp_path)
    c = RL.check_transcript(_lines(f, RL.render("identity", f), attachments=("environment", "nested_memory")),
                            "identity", f)
    assert not c["ok"] and any("unmeasured type: nested_memory" in p for p in c["problems"])


@pytest.mark.parametrize("tool", [("Grep", {"pattern": "91090"}), ("Read", {"file_path": "docs/status.md"}),
                                  ("Bash", {"command": "git log"})])
def test_a_reader_that_looks_beyond_its_file_fails(tmp_path, tool):
    f = _staged(tmp_path)
    c = RL.check_transcript(_lines(f, RL.render("alternative", f), tools=[("Read", {"file_path": f}), tool]),
                            "alternative", f)
    assert not c["ok"]


@pytest.mark.parametrize("report", ["not json", json.dumps({"verdicts": []}),
                                    json.dumps({"verdicts": [{"n": 1, "same_entry": "probably"}]})])
def test_a_report_missing_a_pair_or_malformed_fails(tmp_path, report):
    f = _staged(tmp_path)
    c = RL.check_transcript(_lines(f, RL.render("identity", f), report=report), "identity", f)
    assert not c["ok"]


def _write(dirpath, name, lines):
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / name).write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


def test_the_run_record_carries_the_launcher_hash_and_each_start(tmp_path):
    f = _staged(tmp_path)
    subs = tmp_path / "subagents"
    for i, lens in enumerate(RL.LENSES):
        _write(subs, f"agent-{i}.jsonl", _lines(f, RL.render(lens, f)))
    man = {"run": "t", "since": "2026-10-03T02:00:00Z",
           "readers": [{"pair": "p", "lens": lens, "file": f} for lens in RL.LENSES]}
    rec = RL.check(man, str(subs))
    assert rec["ok"] and rec["launcher"]["sha256"] == RL.launcher()["sha256"]
    assert all(r["start_sha256"] == r["expected_start_sha256"] for r in rec["readers"])
    assert rec["pairs"]["p"]["outcome"] == "unanimous"
    assert rec["tokens"] == 3 * 2051                             # each reader's final context


def test_two_transcripts_for_one_reader_and_an_old_one_are_told_apart(tmp_path):
    f = _staged(tmp_path)
    subs = tmp_path / "subagents"
    _write(subs, "agent-a.jsonl", _lines(f, RL.render("identity", f)))
    _write(subs, "agent-b.jsonl", _lines(f, RL.render("identity", f)))
    _write(subs, "agent-old.jsonl", _lines(f, RL.render("identity", f), began="2026-10-01T00:00:00.000Z"))
    man = {"run": "t", "since": "2026-10-03T02:00:00Z", "readers": [{"pair": "p", "lens": "identity", "file": f}]}
    rec = RL.check(man, str(subs))
    assert not rec["ok"] and rec["readers"][0]["problems"] == ["2 transcripts claim this reader"]


def test_a_workflow_readers_start_is_found_and_failed(tmp_path):
    """The Workflow tool's shape: the relayed request first, then the computed task with
    every line indented. The 2026-10-03 positive control went unfound until the check
    matched the lens and file lines one at a time."""
    f = _staged(tmp_path)
    subs = tmp_path / "subagents"
    task = "[Workflow harness - computed task] follows:\n" + "\n".join(
        "  " + ln for ln in RL.render("identity", f).splitlines())
    _write(subs / "workflows" / "wf_x", "agent-w.jsonl",
           _lines(f, task, before=["[Workflow harness - user request] a brief"]))
    man = {"run": "t", "readers": [{"pair": "p", "lens": "identity", "file": f}]}
    rec = RL.check(man, str(subs))
    assert not rec["ok"] and "not the launcher" in rec["readers"][0]["problems"][0]


@pytest.mark.parametrize("votes, want", [
    ({"a": "yes", "b": "yes", "c": "yes"}, "unanimous"),
    ({"a": "yes", "b": "uncertain", "c": "yes"}, "split"),
    ({"a": "yes", "b": "no", "c": "yes"}, "not linked"),
    ({"a": "yes", "b": "yes"}, "incomplete"),
])
def test_the_outcome_is_the_bar(votes, want):
    assert RL.outcome({k: {"same_entry": v, "better_match": None} for k, v in votes.items()}) == want
    if want == "unanimous":
        votes3 = {k: {"same_entry": "yes", "better_match": None} for k in votes}
        votes3["a"]["better_match"] = 4790
        assert RL.outcome(votes3) == "not linked"                 # a better match is a no

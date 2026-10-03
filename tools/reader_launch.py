"""Blind reads (Corey's rulings, 2026-10-03, ruling 1): every reader starts from the fixed
launcher tools/reader_launcher.txt, rendered for one lens and one file and nothing else, and
every run is checked against it.

    python -m tools.reader_launch stage RECORDS_JSON --dir DIR
    python -m tools.reader_launch render LENS FILE
    python -m tools.reader_launch check MANIFEST --transcripts DIR --out RECORD

`stage` writes a reader's file under a name that is its own content hash, so a path can
carry no label. `render` prints the exact start message to launch one reader with, and
refuses a file whose name is not its content hash. `check` reads every reader's transcript
and fails the run (exit 1) unless each reader:
  - began from the launcher rendered for its lens and file, with nothing before it;
  - received no other message but the harness's fixed hand-back note;
  - was given no context attachment of a type the measured channel does not send;
  - saw none of its pairs' row, object or docket ids anywhere but in its own file;
  - used no tool but Read, on its own file only, and the hand-back;
  - reported one well-formed verdict for every pair in its file.
It writes the run record: the launcher's sha256, each reader's start-message hash, what each
check found, the verdicts, each pair's outcome, and the tokens each reader cost.

WHY THE CHANNEL MATTERS. The Workflow tool hands every agent the user message that started
the turn, verbatim, ahead of its task. A review brief naming a pair's verdict therefore
reached that pair's readers (docs/findings/r1-batching-control-2026-10-03.md). An agent
launched with the Agent tool began from its prompt alone, measured on a probe on
2026-10-03. So briefs go to the main session only, and readers launch by the Agent tool
with the rendered launcher as their whole prompt. This check is what makes that a fact for
each run: run it on a canary before any reader starts, and on the run after.

THE MANIFEST, in the scratchpad and never in a reader's reach:
    {"run": NAME, "since": ISO_Z, "channel": TEXT,
     "readers": [{"pair": LABEL, "lens": LENS, "file": PATH}, ...]}
`since` drops transcripts begun before the run. A reader matched by two transcripts fails:
a relaunch is a new run.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCHER = os.path.join(ROOT, "tools", "reader_launcher.txt")
LENSES = ("identity", "alternative", "clocks")
VERDICTS = ("yes", "no", "uncertain")
NAME = re.compile(r"^[0-9a-f]{12}\.json$")

# What the Agent-tool channel sent a probe on 2026-10-03, besides its prompt. Anything else
# fails the reader until it is measured and added here.
HANDBACK_NOTE = "<system-reminder>\nYour final report is delivered through SubagentHandback"
ATTACHMENTS = frozenset({
    "deferred_tools_delta", "environment", "model", "skill_listing", "session_context", "date",
    "credential_org", "remote_session_change", "prompt_snapshot", "deferred_tools_record",
    "mcp_instructions_delta", "total_tokens_reminder",
})
TOOLS = frozenset({"Read", "SubagentHandback"})


# --------------------------------------------------------------------------- #
# The launcher
# --------------------------------------------------------------------------- #
def launcher(path: str = LAUNCHER) -> dict:
    raw = open(path, "rb").read()
    lines = [ln for ln in raw.decode("utf-8").splitlines() if not (ln == "#" or ln.startswith("# "))]
    parts = re.split(r"^=== lens: (\w+)$", "\n".join(lines), flags=re.M)
    lenses = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}
    if tuple(lenses) != LENSES:
        raise ValueError(f"{path}: lens blocks {tuple(lenses)}, expected {LENSES}")
    return {"template": parts[0].strip(), "lenses": lenses,
            "sha256": hashlib.sha256(raw).hexdigest()}


def content_name(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12] + ".json"


def render(lens: str, file: str, path: str = LAUNCHER) -> str:
    """The whole start message for one reader. The file must be named by its own content
    hash, so the one path a reader is given says nothing about which pair it holds."""
    ln = launcher(path)
    if lens not in ln["lenses"]:
        raise ValueError(f"unknown lens {lens!r}")
    base = os.path.basename(file)
    if not NAME.match(base) or content_name(open(file, "rb").read()) != base:
        raise ValueError(f"{file}: a reader's file must be named by its content hash "
                         f"(`stage` writes it so); this name could carry a label")
    msg = (ln["template"].replace("{{LENS_TEXT}}", ln["lenses"][lens])
           .replace("{{LENS}}", lens).replace("{{FILE}}", file.replace("\\", "/")))
    if "{{" in msg:
        raise ValueError("a slot was left unfilled")
    return msg


def stage(records: list, out_dir: str) -> str:
    data = json.dumps(records, indent=1, ensure_ascii=False).encode("utf-8")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, content_name(data))
    with open(path, "wb") as f:
        f.write(data)
    return path.replace("\\", "/")


# --------------------------------------------------------------------------- #
# The check
# --------------------------------------------------------------------------- #
def _text(content) -> str | None:
    """A user record's text, or None for a record carrying only tool results."""
    if isinstance(content, str):
        return content
    texts = [b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(texts) if texts else None


def _same_path(a: str, b: str) -> bool:
    norm = lambda p: os.path.normcase(os.path.normpath(p.replace("/", os.sep)))
    return norm(a) == norm(b)


def _ids(records: list) -> set[str]:
    """Every id that names a pair in the file: its rows, its objects, its docket."""
    out = set()
    for r in records:
        p = r.get("pair") or {}
        out.update(str(x) for x in (p.get("rows") or []) + (p.get("objects") or []))
        if p.get("case_id"):
            out.add(str(p["case_id"]))
    return out


def _verdict(message: str, ns: list) -> tuple[list | None, str | None]:
    s = message.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    try:
        v = json.loads(s)
    except ValueError:
        return None, "the report is not JSON"
    vs = v.get("verdicts") if isinstance(v, dict) else None
    if not isinstance(vs, list):
        return None, "the report has no verdicts list"
    for x in vs:
        if not (isinstance(x, dict) and x.get("same_entry") in VERDICTS
                and (x.get("better_match") is None or isinstance(x.get("better_match"), int))
                and isinstance(x.get("reasoning"), str) and isinstance(x.get("n"), int)):
            return None, f"a malformed verdict: {json.dumps(x)[:120]}"
    if sorted(x["n"] for x in vs) != sorted(ns):
        return None, f"verdicts for n={sorted(x['n'] for x in vs)}, the file holds n={sorted(ns)}"
    return vs, None


def check_transcript(lines: list, lens: str, file: str, path: str = LAUNCHER) -> dict:
    """Every check on one reader's transcript records. `ok` is True only if all pass."""
    want = render(lens, file, path)
    records = json.load(open(file, encoding="utf-8"))
    ids = _ids(records)
    found = {"start": None, "messages": [], "attachments": [], "ids_outside_file": [],
             "tools": [], "reads_of_file": 0, "verdicts": None, "problems": []}
    users = [d for d in lines if d.get("type") == "user" and _text((d.get("message") or {}).get("content")) is not None]
    if not users:
        found["problems"].append("no start message")
        return {**found, "ok": False}
    first = _text(users[0]["message"]["content"])
    found["start"] = hashlib.sha256(first.strip().encode("utf-8")).hexdigest()
    if first.strip() != want:
        found["problems"].append("the start message is not the launcher rendered for this lens and file")
        found["start_head"] = first.strip()[:160]        # what reached the reader first instead
    for d in users[1:]:
        t = _text(d["message"]["content"])
        found["messages"].append(t[:200])
        if not t.startswith(HANDBACK_NOTE):
            found["problems"].append(f"a message other than the hand-back note: {t[:120]!r}")
    for d in lines:
        if d.get("type") == "attachment":
            kind = (d.get("attachment") or {}).get("type")
            found["attachments"].append(kind)
            if kind not in ATTACHMENTS:
                found["problems"].append(f"an attachment of an unmeasured type: {kind}")
    # The pair's ids may appear only in the result of reading its own file.
    read_ids = set()
    for d in lines:
        m = d.get("message") or {}
        if d.get("type") == "assistant":
            for b in m.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    found["tools"].append(b["name"])
                    if b["name"] not in TOOLS:
                        found["problems"].append(f"a tool outside Read and the hand-back: {b['name']}")
                    elif b["name"] == "Read":
                        target = (b.get("input") or {}).get("file_path", "")
                        if _same_path(target, file):
                            found["reads_of_file"] += 1
                            read_ids.add(b.get("id"))
                        else:
                            found["problems"].append(f"read another file: {target}")
                    elif b["name"] == "SubagentHandback":
                        msg = (b.get("input") or {}).get("message", "")
                        found["verdicts"], why = _verdict(msg, [r.get("n") for r in records])
                        if why:
                            found["problems"].append(why)
    if not found["reads_of_file"]:
        found["problems"].append("never read its file")
    if found["verdicts"] is None and not any("verdict" in p or "report" in p for p in found["problems"]):
        found["problems"].append("no hand-back report")
    # Messages only: an attachment is admitted by its measured type above, and its tool and
    # skill listings carry numbers a four-digit row id could collide with.
    for d in lines:
        if d.get("type") != "user":
            continue
        content = (d.get("message") or {}).get("content")
        if isinstance(content, list) and all(
                isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in read_ids
                for b in content):
            continue              # the file itself
        blob = json.dumps(content, ensure_ascii=False)
        hit = sorted(i for i in ids if re.search(rf"\b{i}\b", blob))
        if hit:
            found["ids_outside_file"].extend(hit)
    if found["ids_outside_file"]:
        found["problems"].append(f"pair ids outside its file: {sorted(set(found['ids_outside_file']))}")
    return {**found, "ok": not found["problems"]}


def tokens(lines: list) -> int:
    """The reader's final context: its largest request, input, cache and output together.
    That is the measure every earlier price used (the harness's per-agent `subagent_tokens`,
    within about a hundred tokens of it). Summing every request instead counts the cached
    context once per request: about three times as much for a reader that reads one file."""
    keys = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
    sizes = [sum(((d.get("message") or {}).get("usage") or {}).get(k) or 0 for k in keys)
             for d in lines if d.get("type") == "assistant" and (d.get("message") or {}).get("usage")]
    return max(sizes, default=0)


def outcome(votes: dict) -> str:
    """The bar: a pass needs all three lenses yes and no better match."""
    if len(votes) < 3:
        return "incomplete"
    if any(v["same_entry"] == "no" or v.get("better_match") for v in votes.values()):
        return "not linked"
    return "unanimous" if all(v["same_entry"] == "yes" for v in votes.values()) else "split"


def _transcripts(root: str, since: str | None) -> list[tuple[str, list]]:
    out = []
    for f in sorted(glob.glob(os.path.join(root, "agent-*.jsonl"))
                    + glob.glob(os.path.join(root, "workflows", "*", "agent-*.jsonl"))):
        lines = [json.loads(ln) for ln in open(f, encoding="utf-8") if ln.strip()]
        began = next((d.get("timestamp") for d in lines if d.get("timestamp")), None)
        if since and (began is None or began < since):
            continue
        out.append((f, lines))
    return out


def check(manifest: dict, transcripts_dir: str, path: str = LAUNCHER) -> dict:
    ln = launcher(path)
    found = _transcripts(transcripts_dir, manifest.get("since"))
    readers, pairs = [], {}
    for r in manifest["readers"]:
        # Each line on its own: the Workflow tool indents every line of a task it relays, and
        # a reader it launched must be found here to be failed for what reached it first.
        marks = (f"Your lens: {r['lens']}\n", f"Your file: {r['file'].replace(chr(92), '/')}")
        mine = [(f, ls) for f, ls in found
                if any(all(m in (_text((d.get("message") or {}).get("content")) or "") + "\n" for m in marks)
                       for d in ls if d.get("type") == "user")]
        rec = {"pair": r["pair"], "lens": r["lens"], "file": os.path.basename(r["file"]),
               "file_sha256": hashlib.sha256(open(r["file"], "rb").read()).hexdigest(),
               "expected_start_sha256": hashlib.sha256(render(r["lens"], r["file"], path).encode("utf-8")).hexdigest(),
               "transcripts": [os.path.basename(f) for f, _ in mine]}
        if len(mine) != 1:
            rec.update(ok=False, problems=[f"{len(mine)} transcripts claim this reader"], tokens=0)
        else:
            c = check_transcript(mine[0][1], r["lens"], r["file"], path)
            if c.get("start_head"):
                rec["start_head"] = c["start_head"]
            rec.update(start_sha256=c["start"], ok=c["ok"], problems=c["problems"],
                       attachments=sorted(set(c["attachments"])), tools=c["tools"],
                       reads_of_file=c["reads_of_file"], verdicts=c["verdicts"],
                       tokens=tokens(mine[0][1]))
            if c["ok"] and c["verdicts"]:
                for v in c["verdicts"]:
                    pairs.setdefault(r["pair"], {})[r["lens"]] = {k: v[k] for k in ("same_entry", "better_match", "reasoning")}
        readers.append(rec)
    return {
        "run": manifest["run"], "channel": manifest.get("channel"),
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "launcher": {"path": "tools/reader_launcher.txt", "sha256": ln["sha256"]},
        "ok": all(r["ok"] for r in readers),
        "readers": readers,
        "pairs": {k: {"outcome": outcome(v), "votes": v} for k, v in pairs.items()},
        "tokens": sum(r["tokens"] for r in readers),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("stage")
    s.add_argument("records")
    s.add_argument("--dir", required=True)
    r = sub.add_parser("render")
    r.add_argument("lens", choices=LENSES)
    r.add_argument("file")
    c = sub.add_parser("check")
    c.add_argument("manifest")
    c.add_argument("--transcripts", required=True)
    c.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "stage":
        print(stage(json.load(open(a.records, encoding="utf-8")), a.dir))
        return 0
    if a.cmd == "render":
        sys.stdout.write(render(a.lens, a.file))
        return 0
    rec = check(json.load(open(a.manifest, encoding="utf-8")), a.transcripts)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rec, f, indent=1, ensure_ascii=False)
        f.write("\n")
    bad = [x for x in rec["readers"] if not x["ok"]]
    print(f"{rec['run']}: {len(rec['readers'])} reader(s), {len(bad)} failed; launcher sha256 "
          f"{rec['launcher']['sha256'][:12]}; {rec['tokens']:,} tokens")
    for x in bad:
        print(f"  FAIL {x['pair']} / {x['lens']}: {'; '.join(x['problems'])}")
    for k, v in rec["pairs"].items():
        print(f"  {k}: {v['outcome']}")
    return 0 if rec["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

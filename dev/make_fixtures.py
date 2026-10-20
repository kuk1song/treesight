#!/usr/bin/env python3
"""Turn the made-up session specs in fixtures/src/*.json into Claude Code shaped transcripts.

Output: fixtures/projects/<project dir>/<session id>.jsonl, the same layout as ~/.claude/projects.
Ids are uuid5 values derived from the spec, so the output is the same on every run.
Record shapes follow transcripts written by Claude Code 2.1.29x; only the fields treesight reads,
plus a few common ones, are filled in.
"""
import json
import os
import sys
import uuid

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/kuk1song/treesight/fixtures")


def uid(*parts):
    return str(uuid.uuid5(NS, "/".join(str(p) for p in parts)))


def ms(t):
    return t[:-1] + ".000Z" if t.endswith("Z") and "." not in t else t


def build(spec):
    sid = uid(spec["session"])
    base = {"isSidechain": False, "userType": "external", "cwd": spec["project"], "sessionId": sid,
            "version": spec["version"], "gitBranch": "main", "entrypoint": "cli"}
    out, parent = [], None

    def add(rec, key):
        nonlocal parent
        rec = dict(base, **rec)
        rec["uuid"] = uid(spec["session"], key)
        rec.setdefault("parentUuid", parent)
        out.append(rec)
        parent = rec["uuid"]
        return rec

    for i, ev in enumerate(spec["events"]):
        k, t = ev["k"], ms(ev["t"])
        if k == "prompt":
            add({"type": "user", "timestamp": t, "message": {"role": "user", "content": ev["text"]},
                 "origin": {"kind": "human"}, "promptSource": "typed", "permissionMode": "default"}, i)
        elif k == "reply":
            add({"type": "assistant", "timestamp": t, "message": {"role": "assistant", "model": "claude-opus-5-5", "type": "message",
                 "content": [{"type": "text", "text": ev["text"]}]}}, i)
        elif k == "tool":
            name, _, arg = ev["text"].partition(" ")
            tool_id = "toolu_" + uid(spec["session"], i, "tool").replace("-", "")[:24]
            a = add({"type": "assistant", "timestamp": t, "message": {"role": "assistant", "model": "claude-opus-5-5", "type": "message",
                     "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": {"command": arg} if name == "Grep" else {"file_path": arg}}]}}, "%d-use" % i)
            add({"type": "user", "timestamp": t, "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_id,
                 "content": "(output of %s)" % ev["text"]}]}, "sourceToolAssistantUUID": a["uuid"]}, "%d-result" % i)
        elif k == "away":
            add({"type": "system", "subtype": "away_summary", "timestamp": t, "content": ev["text"], "isMeta": False}, i)
        elif k == "compact":
            b = add({"type": "system", "subtype": "compact_boundary", "timestamp": t, "content": "Conversation compacted", "level": "info",
                     "logicalParentUuid": parent, "parentUuid": None, "compactMetadata": {"trigger": "auto", "preTokens": 160000, "postTokens": 9000}}, "%d-boundary" % i)
            add({"type": "user", "timestamp": t, "isCompactSummary": True, "isVisibleInTranscriptOnly": True,
                 "message": {"role": "user", "content": ev["text"]}, "parentUuid": b["uuid"]}, "%d-summary" % i)
        elif k == "title":
            out.append({"type": "ai-title", "aiTitle": ev["text"], "sessionId": sid})
        elif k == "custom_title":
            out.append({"type": "custom-title", "customTitle": ev["text"], "sessionId": sid})
        else:
            raise SystemExit("unknown event kind %r in %s" % (k, spec["session"]))
    return sid, out


def main():
    src = os.path.join(ROOT, "fixtures", "src")
    for name in sorted(os.listdir(src)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(src, name), encoding="utf-8") as f:
            spec = json.load(f)
        sid, recs = build(spec)
        # "folder" lets two made-up projects share one path (the English and Chinese demo both live in /home/kuki/recipe-box)
        d = os.path.join(ROOT, "fixtures", "projects", spec.get("folder") or spec["project"].replace("/", "-"))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, sid + ".jsonl"), "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(os.path.relpath(os.path.join(d, sid + ".jsonl"), ROOT), len(recs), "records")
    return 0


if __name__ == "__main__":
    sys.exit(main())

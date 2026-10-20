#!/usr/bin/env python3
"""Run the extraction instructions on one digest several times with `claude -p`, to measure stability.

Each run starts in its own empty directory with no tools, no MCP servers, no skills and no session
saved to disk, and gets extract.md, the two schemas and the digest on stdin. Raw output, the parsed
JSON and a summary line per run go to --out. Outputs of real sessions belong under private/.

Usage: python3 dev/spike_extract.py --digest D.txt --out DIR --label NAME [--runs 3] [--model opus] [--effort low]
"""
import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import tempfile
import time

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import ledger  # noqa: E402


def prompt_for(digest_text):
    read = lambda p: open(os.path.join(ROOT, p), encoding="utf-8").read()
    return ("Follow the instructions below to extract the session in the digest at the end.\n\n"
            + read("skills/treesight/extract.md")
            + "\n\n## Schemas\n\nschema/common.schema.json:\n```json\n" + read("schema/common.schema.json")
            + "\n```\n\nschema/extract.schema.json:\n```json\n" + read("schema/extract.schema.json")
            + "\n```\n\n## Digest\n\n" + digest_text)


def parse_result(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def one(i, args, prompt, digest_text):
    work = tempfile.mkdtemp(prefix="ts-spike-", dir=args.tmp)
    cmd = ["claude", "-p", "--model", args.model] + (["--effort", args.effort] if args.effort else []) + ["--output-format", "json", "--no-session-persistence",
           "--tools", "", "--strict-mcp-config", "--disable-slash-commands", "--max-budget-usd", str(args.budget)]
    t0 = time.time()
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=work, timeout=args.timeout)
    wall = time.time() - t0
    stem = os.path.join(args.out, "run-%s-%d" % (args.label, i))
    with open(stem + ".raw.json", "w", encoding="utf-8") as f:
        f.write(p.stdout)
    row = {"run": i, "exit": p.returncode, "wall_s": round(wall, 1)}
    try:
        raw = json.loads(p.stdout)
        row.update(cost_usd=raw.get("total_cost_usd"), duration_ms=raw.get("duration_ms"), turns=raw.get("num_turns"),
                   usage={k: v for k, v in (raw.get("usage") or {}).items() if k.endswith("tokens")},
                   models=list((raw.get("modelUsage") or {}).keys()), is_error=raw.get("is_error"))
        ext = parse_result(raw.get("result", ""))
        with open(stem + ".json", "w", encoding="utf-8") as f:
            json.dump(ext, f, ensure_ascii=False, indent=1)
        probs = ledger.check(ext, digest_text, args.known_items)
        row.update(nodes=len(ext.get("nodes", [])), open=len(ext.get("open", [])), close=len(ext.get("close", [])),
                   problems=len(probs), problem_sample=probs[:5])
    except Exception as e:  # keep going: a failed run is a data point too
        row.update(error="%s: %s" % (type(e).__name__, e), stderr=p.stderr[-500:])
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--digest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--model", default="opus")
    ap.add_argument("--effort", help="low, medium, high, xhigh or max; default: Claude Code's own")
    ap.add_argument("--budget", type=float, default=10.0)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--tmp", default=None, help="parent directory for the empty working directories")
    ap.add_argument("--known", help="the ledger view the digest was built with, so closes can be checked")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    args.known_items = json.load(open(args.known, encoding="utf-8")) if args.known else None
    digest_text = open(args.digest, encoding="utf-8").read()
    prompt = prompt_for(digest_text)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.runs) as ex:
        rows = list(ex.map(lambda i: one(i, args, prompt, digest_text), range(1, args.runs + 1)))
    with open(os.path.join(args.out, "runs-%s.jsonl" % args.label), "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(dict(r, model=args.model, effort=args.effort, prompt_chars=len(prompt)), ensure_ascii=False) + "\n")
            print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

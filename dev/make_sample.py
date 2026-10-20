#!/usr/bin/env python3
"""Build the sample page docs/demo.html from the made-up tidepool project, the way the plugin would:
digest each session after what the ledger holds, check and append the stored extraction, build the page.

The ledger goes to a temporary TREESIGHT_HOME, removed afterwards, so nothing of the user's own data is touched.
Usage: python3 dev/make_sample.py [--out docs/demo.html]
"""
import argparse
import glob
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
FOLDER = os.path.join(ROOT, "fixtures", "projects", "-home-dev-tidepool")
STEPS = [("953c0ab1", "tidepool-1.json"), ("0a182a7b", "tidepool-2.json")]   # in the order the sessions happened
NOW = "2026-09-24T09:00:00Z"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "demo.html"))
    a = ap.parse_args()
    os.environ["TREESIGHT_HOME"] = tempfile.mkdtemp(prefix="treesight-sample-")
    try:
        return build_sample(a.out)
    finally:
        shutil.rmtree(os.environ["TREESIGHT_HOME"])


def build_sample(out):
    import build, ledger, transcript   # noqa: E401  (after TREESIGHT_HOME is set)
    ledger._now = lambda: NOW          # the runs' own time, so the page is the same every time it is built
    key = ledger.project_key(FOLDER)
    for prefix, name in STEPS:
        path = glob.glob(os.path.join(FOLDER, prefix + "-*.jsonl"))[0]
        with open(os.path.join(ROOT, "fixtures", "extract", name), encoding="utf-8") as f:
            ext = json.load(f)
        state = ledger.load(key)
        after = (state["sessions"].get(ext["session"]) or {}).get("through")
        digest = transcript.digest(path, after=after, known=ledger.known_for(state, ext["session"]))
        probs, _ = ledger.apply(ext, digest, key, model="fixture")
        if probs:
            raise SystemExit("%s: %s" % (name, probs))
    current = json.load(open(os.path.join(ROOT, "fixtures", "extract", STEPS[-1][1]), encoding="utf-8"))["session"]
    return build.main(["--project", FOLDER, "--current", current, "--out", out, "--now", NOW, "--public"])


if __name__ == "__main__":
    sys.exit(main())

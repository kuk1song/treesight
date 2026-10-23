#!/usr/bin/env python3
"""Build a sample page from a made-up project, the way the plugin would:
digest each session after what the ledger holds, check and append the stored extraction, build the page.

recipe-box (the default) is the README demo, docs/demo.html, and recipe-box-zh the same story in Chinese for the
Chinese README's video; tidepool is the project the tests and the measurements in docs/design.md use. The ledger goes to a temporary TREESIGHT_HOME, removed afterwards,
so nothing of the user's own data is touched.
Usage: python3 dev/make_sample.py [--sample recipe-box|recipe-box-zh|tidepool] [--out docs/demo.html]
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
# per sample: its project folder, its sessions with a stored extraction in the order they happened, and the runs' own
# time, which is also the date the page counts days to, so the page is the same every time and for everyone
SAMPLES = {
    "recipe-box": ("-home-kuki-recipe-box", [("0c4f931d", "recipe-1.json"), ("0c0f810a", "recipe-2.json")], "2026-10-03T09:00:00Z"),
    "recipe-box-zh": ("-home-kuki-recipe-box-zh", [("706417bf", "recipe-zh-1.json"), ("e3b89c9b", "recipe-zh-2.json")], "2026-10-03T09:00:00Z"),
    "tidepool": ("-home-dev-tidepool", [("953c0ab1", "tidepool-1.json"), ("0a182a7b", "tidepool-2.json")], "2026-09-24T09:00:00Z"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", choices=sorted(SAMPLES), default="recipe-box")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "demo.html"))
    a = ap.parse_args()
    os.environ["TREESIGHT_HOME"] = tempfile.mkdtemp(prefix="treesight-sample-")
    try:
        return build_sample(a.sample, a.out)
    finally:
        shutil.rmtree(os.environ["TREESIGHT_HOME"])


def build_sample(name, out):
    import build, ledger, transcript   # noqa: E401  (after TREESIGHT_HOME is set)
    project, steps, now = SAMPLES[name]
    folder = os.path.join(ROOT, "fixtures", "projects", project)
    ledger._now = lambda: now          # the runs' own time, so the page is the same every time it is built
    key = ledger.project_key(folder)
    with open(os.path.join(ROOT, "fixtures", "extract", "others.json"), encoding="utf-8") as f:
        others = json.load(f)["samples"].get(name, {})
    for i, (prefix, extract) in enumerate(steps):
        path = glob.glob(os.path.join(folder, prefix + "-*.jsonl"))[0]
        with open(os.path.join(ROOT, "fixtures", "extract", extract), encoding="utf-8") as f:
            ext = json.load(f)
        listed = {}
        if i == 0 and others:      # the first run also summarizes the other sessions, as `show others` would list them
            for sid8, gist in others.items():
                meta = transcript.read_session(glob.glob(os.path.join(folder, sid8 + "-*.jsonl"))[0])[0]
                listed[sid8] = {"id": meta["id"], "upto": meta["last_at"]}
            ext["others"] = [{"session": s, "gist": g} for s, g in others.items()]
        state = ledger.load(key)
        after = (state["sessions"].get(ext["session"]) or {}).get("through")
        digest = transcript.digest(path, after=after, known=ledger.known_for(state, ext["session"]))
        probs, _ = ledger.apply(ext, digest, key, model="fixture", others=listed)
        if probs:
            raise SystemExit("%s: %s" % (extract, probs))
    with open(os.path.join(ROOT, "fixtures", "extract", steps[-1][1]), encoding="utf-8") as f:
        current = json.load(f)["session"]
    return build.main(["--project", folder, "--current", current, "--out", out, "--now", now, "--public"])


if __name__ == "__main__":
    sys.exit(main())

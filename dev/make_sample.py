#!/usr/bin/env python3
"""Build a sample page from a made-up project, the way the plugin would:
digest each session after what the ledger holds, check and append the stored extraction, build the page.

recipe-box (the default) is the README demo, docs/demo.html, and recipe-box-zh the same story in Chinese for the
Chinese README's video; tidepool is the project the tests and the measurements in docs/design.md use. The ledger goes to a temporary TREESIGHT_HOME, removed afterwards,
so nothing of the user's own data is touched.
Usage: python3 dev/make_sample.py [--sample recipe-box|recipe-box-zh|tidepool] [--out docs/demo.html]
       python3 dev/make_sample.py --sample recipe-box --first-run DIR   (the pages and report of a first run, for the video)
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
    ap.add_argument("--first-run", metavar="DIR", help="write pending.html, done.html and report.txt of the sample's first run")
    a = ap.parse_args()
    os.environ["TREESIGHT_HOME"] = tempfile.mkdtemp(prefix="treesight-sample-")
    try:
        return first_run(a.sample, a.first_run) if a.first_run else build_sample(a.sample, a.out)
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


def first_run(name, outdir):
    """The README video's run: the project's first, from its first session. pending.html is the page while that session
    is drawn (no tree yet, the other sessions' overviews being written), done.html the page after it, and report.txt
    the lines build --done gives the user for it, with the page's address as it would be for a project in the
    transcripts' folder (the samples' own folder names differ only so that both demos can share one path)."""
    import build, ledger, transcript, treesight   # noqa: E401  (after TREESIGHT_HOME is set)
    project, steps, now = SAMPLES[name]
    folder = os.path.join(ROOT, "fixtures", "projects", project)
    key = ledger.project_key(folder)
    path = glob.glob(os.path.join(folder, steps[0][0] + "-*.jsonl"))[0]
    meta, entries = transcript.read_session(path)
    with open(os.path.join(ROOT, "fixtures", "extract", "others.json"), encoding="utf-8") as f:
        others = json.load(f)["samples"].get(name, {})
    listed = {}
    for sid8 in others:
        m = transcript.read_session(glob.glob(os.path.join(folder, sid8 + "-*.jsonl"))[0])[0]
        listed[sid8] = {"id": m["id"], "upto": m["last_at"]}
    os.makedirs(outdir, exist_ok=True)
    ledger._now = lambda: now
    pending = [{"session": meta["id"], "title": meta["title"], "estimate_s": 240, "started_at": now}]
    build.write_page(folder, os.path.join(outdir, "pending.html"), current=meta["id"], now=now, pending=pending,
                     public=True, summarizing={v["id"] for v in listed.values()})
    with open(os.path.join(ROOT, "fixtures", "extract", steps[0][1]), encoding="utf-8") as f:
        ext = json.load(f)
    ext["others"] = [{"session": s, "gist": g} for s, g in others.items()]
    done = now[:11] + "09:04:00Z"     # about four minutes later, the estimate above
    ledger._now = lambda: done
    digest = transcript.digest(path, after=None, known=ledger.known_for(ledger.load(key), ext["session"]))
    probs, summary = ledger.apply(ext, digest, key, model="fixture", others=listed)
    if probs:
        raise SystemExit("%s: %s" % (steps[0][1], probs))
    build.write_page(folder, os.path.join(outdir, "done.html"), current=meta["id"], now=done, public=True)
    said = {k: summary.get(k, 0) for k in ("nodes", "open", "closed", "to_confirm")}
    url = "file:///home/kuki/.claude/plugins/data/treesight-treesight/pages/%s.html" % meta["cwd"].replace("/", "-")
    lines = treesight.report({"said": said, "title": meta["title"]}, url, treesight.report_lang(entries)).split("\n")[2:]
    with open(os.path.join(outdir, "report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(json.dumps({"dir": outdir, "said": said, "report": lines}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

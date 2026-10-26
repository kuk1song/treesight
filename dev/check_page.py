#!/usr/bin/env python3
"""Load the page in a headless browser in every view and fail on any script error.

Builds the made-up tidepool project in a temporary folder: a page with no tree yet, one while a run is going on, and a
finished one. Each is loaded with the views and hooks the page knows (#p, #s=, #drawer=1, #expand=, #all=1, and #poke=1,
which clicks every quote mark, drawer item, copy and pause button once), in English and Chinese,
and the browser's console is read from its log.
Needs a Chromium: $CH, else Playwright's chrome-headless-shell, else on Linux google-chrome or chromium. Headless Google
Chrome is not used on macOS, where it leaves app clones behind.

Usage: python3 dev/check_page.py      exit 0: no errors; 1: errors; 2: no browser, or its console cannot be read
"""
import contextlib
import glob
import io
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
S1 = "953c0ab1-134d-56c9-9224-a2eb69918a2a"
VIEWS = ["", "p", "p&drawer=1", "p&expand=p0&poke=1", "s=953c0ab1", "s=953c0ab1&drawer=1&poke=1",
         "s=953c0ab1&expand=953c0ab1-n1&poke=1", "s=953c0ab1&all=1"]


def browser():
    if os.environ.get("CH"):
        return os.environ["CH"]
    home = os.path.expanduser("~")
    for pattern in ("Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell",
                    ".cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell"):
        found = sorted(glob.glob(os.path.join(home, pattern)))
        if found:
            return found[-1]
    if sys.platform.startswith("linux"):
        for name in ("google-chrome", "chromium", "chromium-browser"):
            if shutil.which(name):
                return shutil.which(name)
    return None


def pages(tmp):
    """The three pages, built by the commands the skill runs: no tree yet, a run going on, and a finished run."""
    import treesight
    common = ["--current", S1, "--cache", os.path.join(tmp, "cache")]
    run = lambda *a: treesight.main(list(a) + common)
    env = {"TREESIGHT_HOME": os.path.join(tmp, "home"), "TREESIGHT_WORK": os.path.join(tmp, "work"),
           "TREESIGHT_PROJECTS": os.path.join(ROOT, "fixtures", "projects")}
    saved = {k: os.environ.get(k) for k in env}      # the tests import this module: leave their environment as it was
    os.environ.update(env)
    try:
        return _build(tmp, run)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _build(tmp, run):
    with contextlib.redirect_stdout(io.StringIO()):
        run("build")
        out0 = shutil.copy(glob.glob(os.path.join(tmp, "cache", "pages", "*.html"))[0], os.path.join(tmp, "notree.html"))
        run("prepare")
        run("build", "--session", S1)
        page = glob.glob(os.path.join(tmp, "cache", "pages", "*.html"))[0]
        out = [shutil.copy(page, os.path.join(tmp, "drawing.html"))]
        extract = glob.glob(os.path.join(tmp, "work", "*", "*.digest.txt"))[0].replace(".digest.txt", ".extract.json")
        shutil.copy(os.path.join(ROOT, "fixtures", "extract", "tidepool-1.json"), extract)
        run("apply")
        run("build", "--done", "--session", S1)
    out.append(shutil.copy(page, os.path.join(tmp, "done.html")))
    return [out0] + out


def errors(ch, url, lang, tmp):
    # a fresh profile per load; the keychain and first-run flags keep a full Chrome from spending seconds on each start
    args = [ch, "--user-data-dir=" + tempfile.mkdtemp(dir=tmp), "--use-mock-keychain", "--password-store=basic", "--no-first-run",
            "--enable-logging=stderr", "--v=0", "--lang=" + lang, "--virtual-time-budget=3000", "--dump-dom", url]
    if os.path.basename(ch) != "chrome-headless-shell":
        args[1:1] = ["--headless=new", "--disable-gpu"] + (["--no-sandbox"] if sys.platform.startswith("linux") else [])
    r = subprocess.run(args, capture_output=True, text=True, timeout=60)
    return [line.strip() for line in r.stderr.splitlines() if "CONSOLE" in line and ("Uncaught" in line or "Error" in line)]


def main():
    ch = browser()
    if not ch:
        print("no headless Chromium found; set CH", file=sys.stderr)
        return 2
    tmp = tempfile.mkdtemp(prefix="treesight-check-")
    try:
        canary = os.path.join(tmp, "canary.html")      # this browser's console must be readable, or nothing is checked
        with open(canary, "w", encoding="utf-8") as f:
            f.write("<!doctype html><script>treesightCanary()</script>")
        if not errors(ch, "file://" + canary, "en-US", tmp):
            print("cannot read the console of %s" % ch, file=sys.stderr)
            return 2
        bad = []
        for page in pages(tmp):
            for view in VIEWS:
                for lang in ("en-US", "zh-CN"):
                    for e in errors(ch, "file://%s#%s" % (page, view), lang, tmp):
                        bad.append("%s#%s (%s): %s" % (os.path.basename(page), view, lang, e))
        print("\n".join(bad) or "ok: %d views, no script errors" % (3 * len(VIEWS) * 2))
        return 1 if bad else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Build the treesight page for one project: session metadata read from the transcripts, nodes and
open items from the ledger, drawn by templates/page.html. Needs no model and makes no network request.

The data goes into a non-executing JSON block with <, > and & escaped, so a transcript that contains
</script> cannot end it early, and the page carries a Content Security Policy that allows only its own
script (by hash) and no network access; a page built for the user's own machine also lets that script load the
one-line stamp next to it (see render). Text from transcripts is scrubbed again here: on the user's own
machine secrets, IPv4 addresses and emails are masked; with --public the build also fails if any remain.

Sessions come from the transcripts on disk and from the ledger: a session whose transcript Claude Code has
deleted (after 30 days by default) is still drawn from what the ledger kept, marked as gone.

Usage: python3 build.py --project PROJECT [--current SESSION_ID] [--focus SESSION_ID] [--out FILE] [--now TIME] [--pending JSON]
                        [--public] [--open]
PROJECT is the transcript folder (~/.claude/projects/<key>) or one of its .jsonl files.
"""
import argparse
import base64
import datetime
import glob
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ledger  # noqa: E402
import transcript  # noqa: E402
from schema import Validator  # noqa: E402

TEMPLATE = os.path.normpath(os.path.join(HERE, "..", "templates", "page.html"))
STAMP_S = (2, 5)    # how often an open page reads its stamp: every 2 s while a run is going on, else every 5 s


def _scrub_all(x):
    if isinstance(x, str):
        return transcript.scrub(x)
    if isinstance(x, list):
        return [_scrub_all(v) for v in x]
    if isinstance(x, dict):
        return {k: (v if k in ("id", "msg", "session", "through", "blocked_by", "overturns") else _scrub_all(v)) for k, v in x.items()}
    return x


def _clip(text, n):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "\u2026"


def sessions_in(folder, entries=False):
    """Metadata of every session transcript directly in the folder that has at least one prompt; with entries=True,
    (metadata, entries) pairs."""
    out = []
    for path in sorted(glob.glob(os.path.join(folder, "*.jsonl"))):
        meta, ents = transcript.read_session(path)
        if not meta["id"] or not meta["prompts"]["total"]:
            continue
        out.append((meta, ents) if entries else meta)
    return out


def _kept_meta(sid, led, state):
    """Metadata of a session the ledger has but whose transcript is gone: what the ledger stored at the last run,
    else (ledgers written before 2026-10-16 store none) what its nodes and items tell."""
    m = led.get("meta") or {}
    ats = [n["at"] for n in led["nodes"]] + [o["raised_at"] for o in state["open"] if o.get("session") == sid]
    ats = sorted((x for x in ats if "T" in x), key=transcript.instant) or [led["last_run"]["at"]]   # times only: first_at and last_at are datetimes
    return {"id": sid, "title": m.get("title"), "custom_title": bool(m.get("custom_title")),
            "first_at": m.get("first_at") or ats[0], "last_at": m.get("last_at") or ats[-1],
            "prompts": m.get("prompts") or {"total": 0, "substantive": 0}, "compactions": m.get("compactions") or 0,
            "cwd": m.get("cwd"), "gone": True}


def page_data(folder, current=None, now=None, pending=None, focus=None):
    key = ledger.project_key(folder)
    state = ledger.load(key)
    metas = sessions_in(folder)
    # sessions run with claude -p or the Agent SDK (scripts, tests) are not listed unless they were drawn
    quiet = [m for m in metas if not m["interactive"] and not (state["sessions"].get(m["id"]) or {}).get("runs")]
    metas = [m for m in metas if m not in quiet]
    shown = {m["id"] for m in metas} | {m["id"] for m in quiet}
    files = {os.path.basename(p)[:-len(".jsonl")]: p for p in glob.glob(os.path.join(folder, "*.jsonl"))}
    for sid, led in state["sessions"].items():
        if sid in shown or not led["runs"]:
            continue
        if sid in files:     # on disk but without a prompt now, such as a session where /treesight was the only one
            metas.append(transcript.read_session(files[sid])[0])
        else:
            metas.append(_kept_meta(sid, led, state))
    v = Validator()
    sessions = []
    for m in metas:
        led = state["sessions"].get(m["id"])
        doc = {"schema": "treesight/session@1", "id": m["id"], "title": _clip(transcript.scrub(m["title"] or m["id"][:8]), 200),
               "custom_title": m["custom_title"], "first_at": m["first_at"], "last_at": m["last_at"],
               "prompts": m["prompts"], "compactions": m["compactions"], "generated": bool(led and led["runs"]),
               "nodes": [], "open": []}
        if m.get("gone"):
            doc["gone"] = True
        gist = (led or {}).get("gist")
        if gist:            # the one sentence a run wrote about it (scrubbed first: a mask can be longer than what it hides)
            doc["summary"] = _clip(transcript.scrub(gist["text"]), 300)
        if led and led["runs"]:
            doc["through"] = led["through"]
            doc["nodes"] = led["nodes"]
            lr = led["last_run"]
            doc["last_run"] = {k: lr[k] for k in ("at", "nodes", "open", "closed", "flagged")}
            notes = transcript.scrub((lr.get("notes") or "").strip())     # scrubbed before it is cut, like the summary
            if notes:       # line breaks kept: the page shows the notes as written
                doc["last_run"]["notes"] = notes if len(notes) <= 2000 else notes[:1999] + "\u2026"
        doc["open"] = [{k: v2 for k, v2 in o.items() if k != "session"} for o in state["open"] if o.get("session") == m["id"]]
        doc = _scrub_all(doc)
        errs = v.validate(doc, "session.schema.json")
        if errs:
            raise ValueError("session %s does not match session.schema.json:\n  %s" % (m["id"], "\n  ".join(errs[:10])))
        sessions.append(doc)
    cwd = next((m["cwd"] for m in metas if m.get("cwd")), None) or key
    fixed, now = now is not None, now or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = {"schema": "treesight/page@1", "asof": now, "current": current,
            "project": {"path": transcript.scrub(cwd), "name": os.path.basename(cwd.rstrip("/")) or cwd}, "sessions": sessions}
    if fixed:       # a made-up sample: day counts run to its own date, not to whenever someone opens it
        data["today"] = now
    if sessions:     # the earliest start of any session (the page lists them by last activity)
        data["project"]["first_at"] = min((s["first_at"] for s in sessions), key=transcript.instant)
    if quiet:
        data["hidden"] = len(quiet)
    if focus:
        data["focus"] = focus      # the session this build is about: the page opens on it
    if pending:
        data["pending"] = [dict(p, title=transcript.scrub(p.get("title") or p["session"][:8])) for p in pending]
    return data


def render(data, template=TEMPLATE):
    with open(template, encoding="utf-8") as f:
        html = f.read()
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    blob = blob.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    html = html.replace("__DATA__", blob, 1)
    script = re.findall(r"<script>(.*?)</script>", html, re.S)
    if len(script) != 1:
        raise ValueError("the template must have exactly one executable <script> block")
    digest = base64.b64encode(hashlib.sha256(script[0].encode("utf-8")).digest()).decode()
    # a page on the user's machine also loads its stamp (see write_page): 'strict-dynamic' lets the hashed script insert
    # it and nothing else ('self' would match every local file in Chrome and Safari, and none in Firefox); published
    # pages load nothing but their own script
    html = html.replace("'__SCRIPT_HASH__'", "'sha256-%s'%s" % (digest, " 'strict-dynamic'" if data.get("live") else ""), 1)
    return html


def stamp_path(page):
    """The stamp next to a page: one line of script that names the page's build, so an open page sees a newer one."""
    return re.sub(r"\.html$", "", page) + ".stamp.js"


def stamp_text(data):
    return "window.__treesight&&__treesight(%s);\n" % json.dumps(
        {"v": data["version"], "focus": data.get("focus"), "pending": bool(data.get("pending"))}, separators=(",", ":"))


_IP = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.]*\d)")
# starting only where a run of address characters starts: the same matches, in linear time on a long run without @
_MAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}")


def assert_public(html):
    """For pages that will be published: no address or email may survive."""
    body = html.replace("x.x.x.x", "")
    bad = _IP.findall(body) + _MAIL.findall(body)
    if bad:
        raise ValueError("unmasked address or email in a public page: %s" % sorted(set(bad))[:5])


def write_page(folder, out=None, current=None, now=None, pending=None, focus=None, public=False):
    """Build the page and write it; returns what the build prints. A caller that builds while other runs may append
    to the ledger holds the project lock around this (treesight.py does), so an older state cannot replace a newer page."""
    data = page_data(folder, current, now, pending, focus)
    if not public:      # it keeps itself current: it reads its stamp and reloads when the stamp names a newer build
        data["live"] = True
        data["version"] = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    html = render(data)
    if public:
        assert_public(html)
    out = os.path.abspath(out or os.path.join(ledger.project_dir(ledger.project_key(folder)), "treesight.html"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if public:
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
    else:
        ledger.write_private(out, html)     # in one step: an open page reloading never reads half a file
        ledger.write_private(stamp_path(out), stamp_text(data))     # after the page, so a page it wakes finds the new build
    gen = sum(1 for s in data["sessions"] if s["generated"])
    return {"page": out, "url": pathlib.Path(out).as_uri(), "sessions": len(data["sessions"]), "generated": gen,
            "open": sum(len(s["open"]) for s in data["sessions"])}


_DEFAULT_BROWSER_JS = ('ObjC.import("AppKit"); $.NSWorkspace.sharedWorkspace'
                       '.URLForApplicationToOpenURL($.NSURL.URLWithString("https://example.com")).path.js')


def _browser_command(path):
    """How to ask for the page. With $BROWSER set, Python's webbrowser (which honours it). On macOS, `open -a` with the
    app that opens web links: Python 3.14's webbrowser asks the browser over AppleScript for file URLs, and on
    2026-10-19 that returned success without showing the page, while `open -a` and Python 3.10 showed it.
    `open` alone would use the app for .html files, which can be an editor. Elsewhere, webbrowser."""
    if os.environ.get("BROWSER") or sys.platform != "darwin":
        return None
    try:
        app = subprocess.run(["osascript", "-l", "JavaScript", "-e", _DEFAULT_BROWSER_JS], capture_output=True,
                             text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        app = ""
    return ["open", "-a", app, path] if app.endswith(".app") else ["open", path]


def open_page(res):
    """Ask the browser to show the page. "browser_asked" says the request went out, not that a page is on screen."""
    cmd = _browser_command(res["page"])
    try:
        if cmd:
            res["browser_asked"] = subprocess.run(cmd, capture_output=True, timeout=20).returncode == 0
        else:
            res["browser_asked"] = bool(webbrowser.open("file://" + res["page"]))
    except (OSError, subprocess.SubprocessError, webbrowser.Error):
        res["browser_asked"] = False
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--project", required=True)
    ap.add_argument("--current")
    ap.add_argument("--out")
    ap.add_argument("--now", help="fixed build time for reproducible sample pages; the page counts days to it")
    ap.add_argument("--public", action="store_true", help="fail if any IPv4 address or email remains")
    ap.add_argument("--open", action="store_true", help="open the page in the default browser")
    ap.add_argument("--pending", help="JSON list of {session, title, estimate_s, started_at}: sessions being extracted now; "
                                      "the page says so")
    ap.add_argument("--focus", help="the session this build is about; the page opens on it")
    a = ap.parse_args(argv)
    folder = os.path.expanduser(a.project)
    folder = os.path.dirname(folder) if folder.endswith(".jsonl") else folder
    pending = json.loads(a.pending) if a.pending else None
    if isinstance(pending, dict):
        pending = [pending]
    res = write_page(folder, a.out, a.current, a.now, pending, a.focus, a.public)
    if a.open:
        open_page(res)
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""treesight command line: the steps the skill runs, one subcommand each.

  prepare  find the session, write the digest of its next pass after what the ledger already holds, print JSON
  show     print the extraction guide (instructions and schemas) or one part of the digest, for the model to read
  apply    check the extraction the model wrote and append it to the ledger
  build    build the project page (and open it)
  edit     the user's own change to an item or node: close, reopen, hide, set
  list     sessions of the project, and whether each has a tree

A session is named by id, id prefix, transcript path, or words from its title; with no name it is
--current. Transcripts are looked up in $TREESIGHT_PROJECTS, else $CLAUDE_CONFIG_DIR/projects, else
~/.claude/projects. The digest and the model's extraction live in $TREESIGHT_WORK, else
~/.cache/treesight/work (the skill pre-approves writes under ~/.cache/treesight). Pages and the marks of
runs in progress go to --cache (the skill passes the plugin's data folder), else the ledger home's cache folder.
The ledger itself lives in $TREESIGHT_HOME (see ledger.py). $TREESIGHT_PASS_CHARS sets the size of one digest,
for testing passes on small sessions.
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build  # noqa: E402
import ledger  # noqa: E402
import transcript  # noqa: E402

GUIDE = [os.path.join(HERE, "..", "skills", "treesight", "extract.md"),
         os.path.join(HERE, "..", "schema", "common.schema.json"),
         os.path.join(HERE, "..", "schema", "extract.schema.json")]
PART_CHARS = 20000     # one part of `show`: well under the about 30,000 characters a Bash result shows inline
MAX_PASSES = 2         # passes in one run, so the model's context stays bounded; the next run goes on
JOB_GRACE_S = 20 * 60  # a run counts as stopped once it is this far past its estimate and has not touched its mark for as long


class Problem(Exception):
    pass


def projects_root():
    if os.environ.get("TREESIGHT_PROJECTS"):
        return os.path.expanduser(os.environ["TREESIGHT_PROJECTS"])
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(os.path.expanduser(base), "projects")


def _by_id(prefix):
    if not re.fullmatch(r"[0-9a-f-]{4,36}", prefix or ""):
        return []
    return glob.glob(os.path.join(projects_root(), "*", prefix + "*.jsonl"))


def find_session(name, current=None):
    """Return the transcript path of the named session; words from a title are matched within the current project."""
    name = (name or "").strip()
    if not name:
        if not current:
            raise Problem("no session named and no current session id")
        hits = _by_id(current)
        if not hits:
            raise Problem("the current session %s has no transcript on disk yet" % current)
        return hits[0]
    if name.endswith(".jsonl") and os.path.exists(os.path.expanduser(name)):
        return os.path.abspath(os.path.expanduser(name))
    hits = _by_id(name.lower())
    if not hits:
        here = _by_id(current) if current else []
        folder = os.path.dirname(here[0]) if here else None
        if folder:
            words = name.lower()
            for p in sorted(glob.glob(os.path.join(folder, "*.jsonl"))):
                meta, _ = transcript.read_session(p)
                if meta["title"] and words in meta["title"].lower():
                    hits.append(p)
    if len(hits) != 1:
        raise Problem("%s session matches %r%s" % ("no" if not hits else "more than one", name,
                      "" if not hits else ": " + ", ".join(os.path.basename(h)[:8] for h in hits[:5])))
    return hits[0]


def cache_dir(arg):
    return ledger.private_dir(os.path.expanduser(arg) if arg else os.path.join(ledger.home(), "cache"))


def work_paths(key, sid):
    """The digest the model reads and the extraction it writes. Only the extraction is written by the model."""
    if os.environ.get("TREESIGHT_WORK"):
        root = os.path.expanduser(os.environ["TREESIGHT_WORK"])
    else:
        root = os.path.join(ledger.private_dir(os.path.join(os.path.expanduser("~"), ".cache", "treesight")), "work")
    d = ledger.private_dir(os.path.join(ledger.private_dir(root), key))
    return os.path.join(d, sid[:8] + ".digest.txt"), os.path.join(d, sid[:8] + ".extract.json")


def _remove(*paths):
    for p in paths:
        if os.path.exists(p):
            os.remove(p)


# ---------- marks of runs in progress, so the page can say what is being drawn ----------
def _job_path(cache, key, sid):
    return os.path.join(cache, "jobs", key, sid[:8] + ".json")


def _alive(job):
    """A run is alive while it keeps touching its mark, or until 20 minutes past its estimate. The page says a run
    may have stopped once it is 20 minutes past its estimate; a run still touching its mark then is still "busy",
    which is why the page's words leave that open."""
    now = time.time()
    return now - job.get("touched", 0) < JOB_GRACE_S or now < job.get("started", 0) + job.get("estimate_s", 0) + JOB_GRACE_S


def _load_job(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def read_job(cache, key, sid):
    job = _load_job(_job_path(cache, key, sid))
    return job if job and _alive(job) else None


def write_job(cache, key, sid, job):
    ledger.private_dir(os.path.join(cache, "jobs"))
    ledger.private_dir(os.path.dirname(_job_path(cache, key, sid)))
    job["touched"] = time.time()
    ledger.write_private(_job_path(cache, key, sid), json.dumps(job, ensure_ascii=False))


def touch_job(cache, key, sid):
    job = read_job(cache, key, sid)
    if job:
        write_job(cache, key, sid, job)
    return job


def live_jobs(cache, key):
    out = []
    for p in sorted(glob.glob(os.path.join(cache, "jobs", key, "*.json"))):
        job = _load_job(p)
        if job and _alive(job):
            out.append({k: job[k] for k in ("session", "title", "estimate_s", "started_at") if k in job})
    return out


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- the steps ----------
def session_meta(meta, entries):
    """What the ledger keeps about a session so the page can still show it after its transcript is gone."""
    first = next((e["text"] for e in entries if e["k"] == "P"), "")
    line = meta["summary"] or transcript._short_paste(first, 120)
    out = {k: meta[k] for k in ("custom_title", "first_at", "last_at", "prompts", "compactions", "cwd")}
    out["title"] = transcript.scrub(meta["title"]) if meta["title"] else None
    out["summary"] = transcript.scrub(re.sub(r"\s+", " ", line or "").strip())[:600] or None
    return out


def estimate_s(digest_chars):
    """Extraction time from digest size, fitted on 2026-10-16 runs with Opus at default effort
    (7.6 thousand characters: 127 to 148 s; 136 thousand: 584 to 616 s)."""
    return int(120 + 3.5 * digest_chars / 1000)


def prepare(a):
    path = find_session(a.session, a.current)
    key = ledger.project_key(path)
    meta, entries = transcript.read_session(path)
    cache = cache_dir(a.cache)
    out = {"session": meta["id"], "title": transcript.scrub(meta["title"] or ""), "transcript": path, "project": key}
    with ledger.project_lock(key):
        job = read_job(cache, key, meta["id"])
        if job and not a.go_on:
            out.update(busy=True, started_at=job.get("started_at"))
            return out
        if not job:
            _remove(_job_path(cache, key, meta["id"]))     # the mark of a run that stopped

        state = ledger.load(key)
        led = state["sessions"].get(meta["id"]) or {}
        dig, ext = work_paths(key, meta["id"])
        _remove(dig, ext)    # an extraction left from an earlier try must not be applied by mistake
        text, info = transcript.digest_pass(path, after=led.get("through"), known=ledger.known_for(state, meta["id"]),
                                            max_chars=a.max_chars, loaded=(meta, entries))
        out.update(runs_before=led.get("runs", 0), new_entries=info["new_entries"], nothing_new=not info["new_entries"])
        if not info["new_entries"]:
            if not meta["prompts"]["total"]:
                out["empty"] = True     # no prompt yet, such as a session started only to run /treesight
            return out
        ledger.write_private(dig, text)
        passes = 1 + (job or {}).get("pass", 0) if a.go_on else 1
        this_run = info["pass_chars"][:MAX_PASSES - passes + 1]
        job = job or {"started_at": _now_iso(), "started": time.time(), "estimate_s": sum(estimate_s(c) for c in this_run)}
        write_job(cache, key, meta["id"], {"session": meta["id"], "title": out["title"] or meta["id"][:8], "pass": passes,
                                            "started_at": job["started_at"], "started": job["started"],
                                            "estimate_s": job["estimate_s"],    # the whole run's, from its first pass
                                            "more": info["remaining"] > 0})     # entries this run found but left for a later pass
    out.update(digest_chars=len(text), parts=len(split_parts(text)), extract=ext, pass_number=passes,
               entries_in_this_pass=info["entries"], entries_after_this_pass=info["remaining"],
               estimate_s=estimate_s(len(text)), estimate_run_s=sum(estimate_s(c) for c in this_run))
    return out


def split_parts(text, size=PART_CHARS):
    """The digest in parts of at most `size` characters, broken before an entry where possible, else at a line."""
    parts, cur = [], ""
    pieces = re.split(r"(?m)^(?=\[(?:prompt|reply|recap|compact) \S+ [0-9a-f-]{36}\]$)", text)
    for piece in pieces:
        while len(piece) > size:          # one entry longer than a part: break it at lines, or hard if one line is
            if cur:
                parts.append(cur)
                cur = ""
            cut = piece.rfind("\n", 0, size)
            cut = cut + 1 if cut > size // 2 else size
            parts.append(piece[:cut])
            piece = piece[cut:]
        if len(cur) + len(piece) > size and cur:
            parts.append(cur)
            cur = ""
        cur += piece
    if cur or not parts:
        parts.append(cur)
    return parts


def show(a):
    if a.what == "guide":
        texts = []
        for p in GUIDE:
            with open(p, encoding="utf-8") as f:
                body = f.read().strip()
            texts.append(body if p.endswith(".md") else "# %s\n\n%s" % (os.path.relpath(p, os.path.join(HERE, "..")), body))
        sys.stdout.write("\n\n---\n\n".join(texts) + "\n")
        return None
    path = find_session(a.session, a.current)
    key = ledger.project_key(path)
    sid = transcript.read_session(path)[0]["id"]
    dig, _ = work_paths(key, sid)
    if not os.path.exists(dig):
        raise Problem("no digest for session %s; run prepare first" % sid[:8])
    with open(dig, encoding="utf-8") as f:
        parts = split_parts(f.read())
    if not 1 <= a.part <= len(parts):
        raise Problem("there is no part %d; the digest has %d part(s)" % (a.part, len(parts)))
    touch_job(cache_dir(a.cache), key, sid)
    sys.stdout.write(parts[a.part - 1].rstrip("\n") + "\n\n[end of part %d of %d; %s]\n" % (
        a.part, len(parts), "read part %d next" % (a.part + 1) if a.part < len(parts) else "that was the last part"))
    return None


def apply(a):
    path = find_session(a.session, a.current)
    key = ledger.project_key(path)
    meta, entries = transcript.read_session(path)
    dig, ext = work_paths(key, meta["id"])
    if not os.path.exists(ext):
        raise Problem("no extraction at %s; write it there first" % ext)
    if not os.path.exists(dig):
        raise Problem("no digest for session %s; run prepare first" % meta["id"][:8])
    with open(ext, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except ValueError as e:
            raise Problem("the extraction is not valid JSON: %s" % e)
    with open(dig, encoding="utf-8") as f:
        text = f.read()
    cache = cache_dir(a.cache)
    probs, summary = ledger.apply(data, text, key, model=a.model, meta=session_meta(meta, entries))
    job = touch_job(cache, key, meta["id"])
    if probs:
        return {"ok": False, "problems": probs}
    _remove(dig, ext)
    left = len(transcript.entries_after(path, entries, data["through"]))
    # go on only for entries the run found and could not fit; what the user wrote since waits for the next run
    job = job or {}
    return {"ok": True, **summary, "entries_left": left,
            "go_on": bool(left) and job.get("more", True) and job.get("pass", 1) < MAX_PASSES}


def do_build(a):
    path = find_session(a.session, a.current)
    folder = os.path.dirname(path)
    key = ledger.project_key(path)
    cache = cache_dir(a.cache)
    out = os.path.join(ledger.private_dir(os.path.join(cache, "pages")), key + ".html")
    current = a.current if a.current and _by_id(a.current) else None
    sid = transcript.read_session(path)[0]["id"] if a.session else None
    # Under the project lock from the job marks to the written page: two builds at once (two runs finishing, or a
    # run's progress page and another's result) must not let the one that read the older state write last.
    with ledger.project_lock(key):
        if sid and a.done:                          # this run is over, finished or not: its mark and work files go
            _remove(_job_path(cache, key, sid), *work_paths(key, sid))
        res = build.write_page(folder, out, current, pending=live_jobs(cache, key) or None, focus=sid)
    if a.open:
        build.open_page(res)
    print(json.dumps(res, ensure_ascii=False))
    return None


_POOLS = {"close": ("open",), "reopen": ("closed", "unsure"), "hide": ("open", "nodes"), "set": ("open", "nodes")}


def _resolve_target(key, action, target):
    state = ledger.load(key)
    groups = {"open": state["open"], "closed": state["closed"], "nodes": [n for s in state["sessions"].values() for n in s["nodes"]],
              "unsure": [o for o in state["open"] if o["state"] in ("confirm", "stale")]}
    if target in {x["id"] for g in groups.values() for x in g}:
        return target
    words = target.lower()
    hits = [x["id"] for g in _POOLS[action] for x in groups[g] if words in x["label"].lower()]
    if len(hits) != 1:
        kinds = " or ".join({"open": "open items", "closed": "closed items", "nodes": "nodes", "unsure": "items to confirm"}[g]
                            for g in _POOLS[action])
        raise Problem("%s of the %s matches %r%s" % ("none" if not hits else "more than one", kinds, target,
                                                     "" if not hits else ": " + ", ".join(hits[:5])))
    return hits[0]


def edit(a):
    path = find_session(a.session, a.current)
    key = ledger.project_key(path)
    fields = {}
    for f in a.fields:
        if "=" not in f:
            raise Problem("--field %r: expected FIELD=VALUE" % f)
        k, v = f.split("=", 1)
        fields[k.strip()] = v.strip()
    for k in ("rank", "score"):
        if fields.get(k):
            if not re.fullmatch(r"-?\d+", fields[k]):
                raise Problem("%s must be a whole number, not %r" % (k, fields[k]))
            fields[k] = int(fields[k])
    return ledger.edit(key, a.action, _resolve_target(key, a.action, " ".join(a.target)), fields)


def list_sessions(a):
    path = find_session(a.session, a.current)
    key = ledger.project_key(path)
    state = ledger.load(key)
    rows = []
    for m in build.sessions_in(os.path.dirname(path)):
        led = state["sessions"].get(m["id"]) or {}
        rows.append({"id": m["id"][:8], "title": transcript.scrub(m["title"] or ""), "last_at": m["last_at"],
                     "prompts": m["prompts"]["substantive"], "tree": bool(led.get("runs"))})
    return sorted(rows, key=lambda r: r["last_at"], reverse=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    cmds = {}
    for name in ("prepare", "show", "apply", "build", "edit", "list"):
        p = sub.add_parser(name)
        p.add_argument("--session", default="", help="id, id prefix, transcript path or title words; empty means --current")
        p.add_argument("--current", help="the session the user is in (the skill passes its id)")
        p.add_argument("--cache")
        cmds[name] = p
    cmds["prepare"].add_argument("--max-chars", type=int, default=int(os.environ.get("TREESIGHT_PASS_CHARS") or transcript.PASS_CHARS))
    cmds["prepare"].add_argument("--continue", dest="go_on", action="store_true", help="the next pass of the run that is going on")
    cmds["show"].add_argument("what", choices=["guide", "digest"])
    cmds["show"].add_argument("--part", type=int, default=1)
    cmds["apply"].add_argument("--model")
    cmds["build"].add_argument("--open", action="store_true")
    cmds["build"].add_argument("--done", action="store_true", help="the run for --session is over, so stop showing it as in progress")
    cmds["edit"].add_argument("action", choices=["close", "reopen", "hide", "set"])
    cmds["edit"].add_argument("target", nargs="+", help="an id, or words from the item's label")
    cmds["edit"].add_argument("--field", dest="fields", action="append", default=[], help="FIELD=VALUE, for set; repeat")
    a = ap.parse_args(argv)
    t0 = time.time()
    try:
        res = {"prepare": prepare, "show": show, "apply": apply, "build": do_build, "edit": edit, "list": list_sessions}[a.cmd](a)
    except (Problem, ValueError, OSError) as e:     # the skill reads {"ok": false} rather than a traceback
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1
    if res is not None:
        if isinstance(res, dict):
            res.setdefault("seconds", round(time.time() - t0, 2))
        print(json.dumps(res, ensure_ascii=False, indent=1))
        if isinstance(res, dict) and res.get("ok") is False:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

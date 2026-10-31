#!/usr/bin/env python3
"""treesight command line: the steps the skill runs, one subcommand each.

  prepare  find the session, write the digest of its next pass after what the ledger already holds, print JSON
  show     print the extraction guide (instructions and schemas), one part of the digest, or the excerpts of other
           sessions to summarize, for the model to read
  apply    check the extraction the model wrote and append it to the ledger
  build    build the project page (and ask the browser to open it, once per conversation)
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
PART_BYTES = 24000     # one part of `show`, in UTF-8 bytes: Claude Code shows a Bash result inline only up to about
                       # 30,000 bytes (2026-10-21: 25,000 bytes of Chinese shown inline, 33,000 saved to a file instead)
MAX_PASSES = 2         # passes in one run, so the model's context stays bounded; the next run goes on
OTHERS_MAX = 30        # other sessions one run summarizes at most (the most recent first); the next run does the rest
OTHER_S = 6            # seconds per other session in the estimate (one 2026-10-23 run: about 86 s more with 14, twig rule included)
JOB_GRACE_S = 20 * 60  # a run counts as stopped once it is this far past its estimate and has not touched its mark for as long


class Problem(Exception):
    pass


def projects_root():
    if os.environ.get("TREESIGHT_PROJECTS"):
        return os.path.expanduser(os.environ["TREESIGHT_PROJECTS"])
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return os.path.join(os.path.expanduser(base), "projects")


def _by_id(prefix, folder=None):
    """Transcripts whose id starts with the prefix: in the folder given, else in every project, but there only for 8
    characters or more, so a number in a title (8080, 2026) is not taken for a session of another project."""
    if not re.fullmatch(r"[0-9a-f-]{4,36}", prefix or "") or (folder is None and len(prefix) < 8):
        return []
    return glob.glob(os.path.join(folder or os.path.join(projects_root(), "*"), prefix + "*.jsonl"))


def matching(words, items, text):
    """The items whose text holds the words: as one phrase if any does, else each word anywhere, in any order."""
    words = words.lower().split()
    flat = [" ".join((text(x) or "").lower().split()) for x in items]
    hits = [x for x, t in zip(items, flat) if " ".join(words) in t]
    return hits or [x for x, t in zip(items, flat) if all(w in t for w in words)]


def find_session(name, current=None):
    """Return the transcript path of the named session: an id or id prefix, or words from a title of the current
    project (as one phrase, or each word anywhere)."""
    name = (name or "").strip()
    here = _by_id(current) if current else []
    if not name:
        if not current:
            raise Problem("no session named and no current session id")
        if not here:
            raise Problem("the current session %s has no transcript on disk yet" % current)
        return here[0]
    if name.endswith(".jsonl") and os.path.exists(os.path.expanduser(name)):
        return os.path.abspath(os.path.expanduser(name))
    folder = os.path.dirname(here[0]) if here else None
    hits = (_by_id(name.lower(), folder) if folder else []) or _by_id(name.lower())
    titled = {}
    if not hits and folder:
        for p in sorted(glob.glob(os.path.join(folder, "*.jsonl"))):
            titled[p] = transcript.read_session(p)[0]["title"] or ""     # matched as written; scrubbed only when shown
        hits = matching(name, list(titled), titled.get)
    if len(hits) != 1:
        named = [os.path.basename(h)[:8] + (" \u201c%s\u201d" % transcript.scrub(titled[h]) if titled.get(h) else "") for h in hits[:5]]
        raise Problem("%s session matches %r%s" % ("no" if not hits else "more than one", name, ": " + ", ".join(named) if hits else ""))
    return hits[0]


def read_session(path):
    """transcript.read_session, for a session that has messages: a transcript with none (only a title, say) has no
    session id inside it."""
    meta, entries = transcript.read_session(path)
    if not meta["id"]:
        raise Problem("%s has no messages yet" % os.path.basename(path))
    return meta, entries


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


def others_paths(key, sid):
    """Next to the digest: the excerpts of the other sessions this run summarizes, which the model reads, and which
    sessions those are, which apply reads (not from the run's mark, which can expire before the run applies)."""
    base = work_paths(key, sid)[0][:-len(".digest.txt")]
    return base + ".others.txt", base + ".others.json"


def said_last(meta, entries):
    """When a session last said something of its own: its last entry, not a later /treesight command or notice, so
    the conversation that runs treesight does not look changed every time."""
    return max((e["at"] for e in entries), key=transcript.instant, default=meta["last_at"])


def to_summarize(folder, state, sid, sessions=None):
    """Other sessions of the project that need a one-sentence summary, the most recent first: an interactive session
    without a tree whose summary is missing or older than its last entry, or a drawn session that has none (a drawn
    session's own run writes it from the whole session, so an excerpt only fills a gap). sessions: what
    build.sessions_in(folder, entries=True) gives, when the caller has read it already."""
    out = []
    for meta, entries in sessions if sessions is not None else build.sessions_in(folder, entries=True):
        led = state["sessions"].get(meta["id"]) or {}
        gist = led.get("gist")
        if meta["id"] == sid or not meta["interactive"] and not led.get("runs"):
            continue
        if not gist:
            stale = True
        elif led.get("runs"):
            stale = False
        else:
            stale = not gist.get("upto") or transcript.instant(gist["upto"]) < transcript.instant(said_last(meta, entries))
        if stale:
            out.append((meta, entries))
    out.sort(key=lambda x: transcript.instant(said_last(*x)), reverse=True)
    return out[:OTHERS_MAX]


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


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def read_job(cache, key, sid):
    job = _load_json(_job_path(cache, key, sid))
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
        job = _load_json(p)
        if job and _alive(job):
            out.append({k: job[k] for k in ("session", "title", "estimate_s", "started_at") if k in job})
    return out


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- the steps ----------
def session_meta(meta, entries):
    """What the ledger keeps about a session so the page can still show it after its transcript is gone."""
    out = {k: meta[k] for k in ("custom_title", "first_at", "last_at", "prompts", "compactions", "cwd")}
    out["title"] = transcript.scrub(meta["title"]) if meta["title"] else None
    out["summary"] = re.sub(r"\s+", " ", transcript.session_line(meta, entries)).strip()[:600] or None
    return out


def estimate_s(digest_chars):
    """Extraction time from digest size, fitted on 2026-10-16 runs with Opus at default effort
    (7.6 thousand characters: 127 to 148 s; 136 thousand: 584 to 616 s)."""
    return int(120 + 3.5 * digest_chars / 1000)


def prepare(a):
    words = a.session.split()       # flags left among the session words
    if "--restart" in words:
        a.restart = True
    no_open = "--no-open" in words  # the page's own links add it: the page is open, so this conversation must not open it again
    a.session = " ".join(w for w in words if w not in ("--restart", "--no-open"))
    path = find_session(a.session, a.current)
    key = ledger.project_key(path)
    meta, entries = read_session(path)
    cache = cache_dir(a.cache)
    if no_open:
        mark_opened(cache, key, a.current)
    # read before taking the project lock, which other runs' builds wait for: a first pass may summarize other sessions
    sessions = None if a.go_on else build.sessions_in(os.path.dirname(path), entries=True)
    out = {"session": meta["id"], "title": transcript.scrub(meta["title"] or ""), "transcript": path, "project": key}
    with ledger.project_lock(key):
        job = read_job(cache, key, meta["id"])
        if job and a.restart and not a.go_on:
            job = None          # the user stopped that run; if it was still going, the ledger takes only the first to apply
        if job and not a.go_on:
            free = max(job.get("touched", 0), job.get("started", 0) + job.get("estimate_s", 0)) + JOB_GRACE_S
            out.update(busy=True, started_at=job.get("started_at"), free_in_min=max(1, int((free - time.time()) // 60) + 1))
            return out
        if not job:
            _remove(_job_path(cache, key, meta["id"]))     # the mark of a run that stopped

        state = ledger.load(key)
        led = state["sessions"].get(meta["id"]) or {}
        dig, ext = work_paths(key, meta["id"])
        oth, oth_ids = others_paths(key, meta["id"])
        _remove(dig, ext, oth, oth_ids)    # an extraction left from an earlier try must not be applied by mistake
        text, info = transcript.digest_pass(path, after=led.get("through"), known=ledger.known_for(state, meta["id"]),
                                            max_chars=a.max_chars, loaded=(meta, entries))
        out.update(runs_before=led.get("runs", 0), new_entries=info["new_entries"], nothing_new=not info["new_entries"])
        if not info["new_entries"]:
            if not meta["prompts"]["total"]:
                out["empty"] = True     # no prompt yet, such as a session started only to run /treesight
            return out
        ledger.write_private(dig, text)
        passes = 1 + (job or {}).get("pass", 0) if a.go_on else 1
        # the first pass also summarizes the project's other sessions that need it, each from a short excerpt
        others = to_summarize(os.path.dirname(path), state, meta["id"], sessions) if passes == 1 else []
        oth_text = "\n\n".join("[session %s]\n%s" % (m["id"][:8], transcript.overview(m, e)) for m, e in others) + "\n"
        if others:
            ledger.write_private(oth, oth_text)
            ledger.write_private(oth_ids, json.dumps({m["id"][:8]: {"id": m["id"], "upto": said_last(m, e)} for m, e in others}))
        this_run = info["pass_chars"][:MAX_PASSES - passes + 1]
        job = job or {"started_at": _now_iso(), "started": time.time(),
                      "estimate_s": sum(estimate_s(c) for c in this_run) + OTHER_S * len(others)}
        write_job(cache, key, meta["id"], {"session": meta["id"], "title": out["title"] or meta["id"][:8], "pass": passes,
                                            "started_at": job["started_at"], "started": job["started"],
                                            "estimate_s": job["estimate_s"],    # the whole run's, from its first pass
                                            "more": info["remaining"] > 0})     # entries this run found but left for a later pass
    out.update(digest_chars=len(text), parts=len(split_parts(text)), extract=ext, pass_number=passes, others=len(others),
               others_parts=len(split_parts(oth_text, head=OTHER_HEAD)) if others else 0,
               entries_in_this_pass=info["entries"], entries_after_this_pass=info["remaining"],
               estimate_s=estimate_s(len(text)), estimate_run_s=sum(estimate_s(c) for c in this_run))
    return out


def _bytes(text):
    return len(text.encode("utf-8"))


ENTRY_HEAD = r"(?m)^(?=\[(?:prompt|reply|recap|compact) \S+ [0-9a-f-]{36}\]$)"
OTHER_HEAD = r"(?m)^(?=\[session [0-9a-f]{8}\]$)"


def split_parts(text, size=None, head=ENTRY_HEAD):
    """The digest (or the excerpts of other sessions, head=OTHER_HEAD) in parts of at most `size` UTF-8 bytes, broken
    before an entry where possible, else at a line."""
    size = size or PART_BYTES
    parts, cur, cur_b = [], "", 0
    pieces = re.split(head, text)
    for piece in pieces:
        while _bytes(piece) > size:       # one entry longer than a part: break it at lines, or hard if one line is
            if cur:
                parts.append(cur)
                cur, cur_b = "", 0
            fit = len(piece.encode("utf-8")[:size].decode("utf-8", "ignore"))    # characters that fit in `size` bytes
            cut = piece.rfind("\n", 0, fit)
            cut = cut + 1 if cut > fit // 2 else fit
            parts.append(piece[:cut])
            piece = piece[cut:]
        b = _bytes(piece)
        if cur_b + b > size and cur:
            parts.append(cur)
            cur, cur_b = "", 0
        cur += piece
        cur_b += b
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
    sid = read_session(path)[0]["id"]
    if a.what == "others":
        src, head = others_paths(key, sid)[0], OTHER_HEAD
        if not os.path.exists(src):
            raise Problem("no other sessions to summarize for session %s" % sid[:8])
    else:
        src, head = work_paths(key, sid)[0], ENTRY_HEAD
        if not os.path.exists(src):
            raise Problem("no digest for session %s; run prepare first" % sid[:8])
    with open(src, encoding="utf-8") as f:
        parts = split_parts(f.read(), head=head)
    if not 1 <= a.part <= len(parts):
        raise Problem("there is no part %d; the digest has %d part(s)" % (a.part, len(parts)))
    touch_job(cache_dir(a.cache), key, sid)
    sys.stdout.write(parts[a.part - 1].rstrip("\n") + "\n\n[end of part %d of %d; %s]\n" % (
        a.part, len(parts), "read part %d next" % (a.part + 1) if a.part < len(parts) else "that was the last part"))
    return None


def apply(a):
    path = find_session(a.session, a.current)
    key = ledger.project_key(path)
    meta, entries = read_session(path)
    dig, ext = work_paths(key, meta["id"])
    if not os.path.exists(dig):     # first: when another run of the session has finished, both files are gone
        raise Problem("no digest for session %s; run prepare first" % meta["id"][:8])
    if not os.path.exists(ext):
        raise Problem("no extraction at %s; write it there first" % ext)
    with open(ext, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except ValueError as e:
            raise Problem("the extraction is not valid JSON: %s" % e)
    with open(dig, encoding="utf-8") as f:
        text = f.read()
    cache = cache_dir(a.cache)
    job = touch_job(cache, key, meta["id"]) or {}
    oth, oth_ids = others_paths(key, meta["id"])
    probs, summary = ledger.apply(data, text, key, model=a.model, meta=session_meta(meta, entries), pass_number=job.get("pass", 1),
                                  others=_load_json(oth_ids) or {})
    if probs:
        return {"ok": False, "problems": probs}
    _remove(dig, ext, oth, oth_ids)
    left = len(transcript.entries_after(path, entries, data["through"]))
    if job:     # for the report build --done writes: apply's counts already cover every pass of this run
        job["said"] = dict({k: summary.get(k, 0) for k in ("nodes", "open", "closed", "to_confirm")}, entries_left=left)
        write_job(cache, key, meta["id"], job)
    # go on only for entries the run found and could not fit; what the user wrote since waits for the next run
    return {"ok": True, **summary, "entries_left": left,
            "go_on": bool(left) and job.get("more", True) and job.get("pass", 1) < MAX_PASSES}


def do_build(a):
    path = find_session(a.session, a.current)
    folder = os.path.dirname(path)
    key = ledger.project_key(path)
    cache = cache_dir(a.cache)
    out = os.path.join(ledger.private_dir(os.path.join(cache, "pages")), key + ".html")
    current = a.current if a.current and _by_id(a.current) else None
    meta, entries = transcript.read_session(path) if a.session else (None, None)
    sid = meta["id"] if meta else None
    kept = os.path.join(cache, "current", key + ".json")
    # Under the project lock from the job marks to the written page: two builds at once (two runs finishing, or a
    # run's progress page and another's result) must not let the one that read the older state write last.
    with ledger.project_lock(key):
        job = _load_json(_job_path(cache, key, sid)) if sid and a.done else None
        if sid and a.done:                          # this run is over, finished or not: its mark and work files go
            _remove(_job_path(cache, key, sid), *work_paths(key, sid), *others_paths(key, sid))
        jobs = live_jobs(cache, key)
        # sessions whose overview a run that is going on is writing: those its first pass listed
        summarizing = {o["id"] for j in jobs for o in (_load_json(others_paths(key, j["session"])[1]) or {}).values()}
        res = build.write_page(folder, out, current, pending=jobs or None, focus=sid, summarizing=summarizing,
                               keep_current=(_load_json(kept) or {}).get("id"))
        if current and res["current"] == current:   # a conversation of its own, listed: the one to keep marking
            ledger.private_dir(os.path.dirname(kept))
            ledger.write_private(kept, json.dumps({"id": current}))
    if a.open:
        open_once(cache, key, a.current, res)
    if job and job.get("said"):
        res["report"] = report(job, res["url"], report_lang(entries))
    print(json.dumps(res, ensure_ascii=False))
    return None


# ---------- what the user reads in the conversation when a run is done (the plugin's hook asks Claude to show it as is) ----------
REPORT_HEAD = "treesight finished. This report is for the user; nothing else needs doing."


def report_lang(entries):
    """The language of the session's prompts, for the report: Chinese when its last prompts hold more Chinese
    characters than English words (pasted text and code left out), else English."""
    text = " ".join([e["text"] for e in entries if e["k"] == "P"][-20:])
    text = re.sub(r"<pasted_content[^>]*>.*?</pasted_content[^>]*>|```.*?```|`[^`]*`", " ", text, flags=re.S)
    return "zh" if len(re.findall("[\u3400-\u9fff]", text)) > len(re.findall(r"[A-Za-z]+", text)) else "en"


def report(job, url, lang):
    """The run's report: the fixed first line for the main conversation, then two lines for the user (what changed,
    with only what is not zero, and the page's link), and a line more only when something needs the user."""
    said, title = job["said"], job.get("title") or job.get("session", "")[:8]
    n, o, c, k, left = (said.get(x, 0) for x in ("nodes", "open", "closed", "to_confirm", "entries_left"))
    if lang == "zh":
        added = "、".join(x for x in ("%d 个节点" % n if n else "", "%d 件待完成" % o if o else "") if x)
        body = "，".join(x for x in ("新增 " + added if added else "", "关掉 %d 件" % c if c else "") if x) or "这次没有新内容"
        lines = ["🌳 treesight：「%s」的树已生成，%s。" % (title, body), "页面已更新：%s" % url]
        if k:
            lines.append("有 %d 件看起来做完了，等你在页面上确认。" % k)
        if left:
            lines.append("这个会话还有 %d 条没读，再运行一次会接着读。" % left)
    else:
        pl = lambda x, one, many: "%d %s" % (x, one if x == 1 else many)
        body = ", ".join(x for x in (pl(n, "new node", "new nodes") if n else "", pl(o, "new open item", "new open items") if o else "",
                                     "%d closed" % c if c else "") if x)
        lines = ["🌳 treesight: the tree of \u201c%s\u201d is ready%s." % (title, " (%s)" % body if body else ", with nothing new this time"),
                 "Page updated: %s" % url]
        if k:
            lines.append("%s done; confirm %s on the page." % (pl(k, "item looks", "items look"), "it" if k == 1 else "them"))
        if left:
            lines.append("%s of this session %s not read yet; run treesight again to read %s." % (
                pl(left, "message", "messages"), "is" if left == 1 else "are", "it" if left == 1 else "them"))
    return "\n".join([REPORT_HEAD, ""] + lines)


OPEN_KEEP_S = 3 * 3600    # a conversation that has not updated its page for this long gets it opened again (resumed later)


def open_once(cache, key, current, res):
    """Ask the browser to show the page once per conversation. Later runs and corrections in the same conversation do
    not open another tab: the page already open reads its stamp and reloads itself (build.stamp_path). A conversation
    resumed after a pause of three hours or more gets the page opened again, since its tab is likely gone."""
    seen = _load_json(os.path.join(cache, "opened", key + ".json"))
    seen = seen if isinstance(seen, dict) else {}
    if current and time.time() - seen.get(current, 0) < OPEN_KEEP_S:
        res.update(browser_asked=False, open_page_updates=True)
    else:
        build.open_page(res)
    if current and (res.get("browser_asked") or res.get("open_page_updates")):
        mark_opened(cache, key, current)
    return res


def mark_opened(cache, key, current):
    """Note that this conversation's page is open (it was asked for, or a run started from the page's own link)."""
    if not current:
        return
    path = os.path.join(cache, "opened", key + ".json")
    seen = _load_json(path)
    seen = seen if isinstance(seen, dict) else {}
    seen[current] = time.time()
    keep = dict(sorted(seen.items(), key=lambda kv: kv[1])[-50:])
    ledger.private_dir(os.path.dirname(path))
    ledger.write_private(path, json.dumps(keep))


_POOLS = {"close": ("open",), "reopen": ("closed", "unsure"), "hide": ("open", "nodes"), "set": ("open", "nodes")}


def _resolve_target(key, action, target):
    state = ledger.load(key)
    groups = {"open": state["open"], "closed": state["closed"], "nodes": [n for s in state["sessions"].values() for n in s["nodes"]],
              "unsure": [o for o in state["open"] if o["state"] in ("confirm", "stale")]}
    if target in {x["id"] for g in groups.values() for x in g}:
        return target
    pool = [x for g in _POOLS[action] for x in groups[g]]
    hits = list({x["id"]: x for x in matching(target, pool, lambda x: x["label"])}.values())
    if len(hits) != 1:
        kinds = " or ".join({"open": "open items", "closed": "closed items", "nodes": "nodes", "unsure": "items to confirm"}[g]
                            for g in _POOLS[action])
        raise Problem("%s of the %s matches %r%s" % ("none" if not hits else "more than one", kinds, target, "" if not hits else
                      "; use more of the words: " + ", ".join("\u201c%s\u201d" % x["label"] for x in hits[:5])))
    return hits[0]["id"]


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
    if fields.get("blocked_by"):        # the item that has to happen first, by id or by words from its label
        fields["blocked_by"] = _resolve_target(key, "close", fields["blocked_by"])
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


class _Parser(argparse.ArgumentParser):
    def error(self, message):       # a wrong argument also answers {"ok": false}, which the skill reads, not a usage text
        raise Problem(message)


def main(argv=None):
    ap = _Parser(description=__doc__.split("\n\n")[0])
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
    cmds["prepare"].add_argument("--restart", action="store_true", help="start although a run of this session seems to be going on "
                                 "(one the user stopped); a run that is in fact still going cannot record the same entries twice")
    cmds["show"].add_argument("what", choices=["guide", "digest", "others"])
    cmds["show"].add_argument("--part", type=int, default=1)
    cmds["apply"].add_argument("--model")
    cmds["build"].add_argument("--open", action="store_true")
    cmds["build"].add_argument("--done", action="store_true", help="the run for --session is over, so stop showing it as in progress")
    cmds["edit"].add_argument("action", choices=["close", "reopen", "hide", "set"])
    cmds["edit"].add_argument("target", nargs="+", help="an id, or words from the item's label")
    cmds["edit"].add_argument("--field", dest="fields", action="append", default=[], help="FIELD=VALUE, for set; repeat")
    t0 = time.time()
    try:
        a = ap.parse_args(argv)
        res = {"prepare": prepare, "show": show, "apply": apply, "build": do_build, "edit": edit, "list": list_sessions}[a.cmd](a)
    except (Problem, ValueError, OSError) as e:     # the skill reads {"ok": false} rather than a traceback
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1
    except Exception as e:      # what nobody foresaw (a transcript format change, say): still an answer, with its kind
        print(json.dumps({"ok": False, "error": "unexpected %s: %s" % (type(e).__name__, e)}, ensure_ascii=False))
        return 1
    if res is not None:
        if isinstance(res, dict):
            res.setdefault("seconds", round(time.time() - t0, 2))
        print(json.dumps(res, ensure_ascii=False, indent=1))
        if isinstance(res, dict) and res.get("ok") is False:
            return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")      # the JSON holds Chinese and the report's 🌳, whatever the console's code page
    sys.exit(main())

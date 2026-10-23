#!/usr/bin/env python3
"""The treesight ledger: an append-only record of what extraction found, one per project.

Files live in $TREESIGHT_HOME, else $XDG_DATA_HOME/treesight, else ~/.local/share/treesight, under
projects/<project key>/ (the key is the folder name Claude Code uses under ~/.claude/projects):
  ledger.jsonl  what the model added or proposed to close; lines are only ever appended
  edits.jsonl   the user's own changes; applied last, so they always win

Before anything is appended, an extraction output must match schema/extract.schema.json, every
message id must be an entry of the digest the model read, every quote must appear in that entry and
every time must be that entry's, refs must resolve, and closes may only name items that are still open
in the project and quote nothing said before the item was raised. "settled" may only name later records
that the digest's header listed (see known_for); the ledger copies their quotes.

Usage (PROJECT is the transcript's folder or file, or --project=KEY; keys start with "-"):
  python3 ledger.py check <extract.json> <digest.txt> [--project PROJECT]
  python3 ledger.py apply <extract.json> <digest.txt> --project PROJECT [--model NAME]
  python3 ledger.py view  --project PROJECT
  python3 ledger.py edit  --project PROJECT close|reopen|hide <id>
  python3 ledger.py edit  --project PROJECT set <id> FIELD=VALUE ...
"""
import argparse
import contextlib
import copy
import datetime
import json
import os
import re
import sys
import uuid

try:
    import fcntl
except ImportError:  # Windows: no lock, single writer assumed
    fcntl = None

from schema import Validator
from transcript import instant

_BLOCK = re.compile(r"^\[(prompt|reply|recap|compact) (\S+) ([0-9a-f-]{36})\]\n", re.M)


def parse_digest(text):
    """Entries of a digest as {msg: {"kind", "at", "text"}} in order, plus the session id from the header."""
    m = re.search(r"^session: (\S+)$", text, re.M)
    entries = {}
    marks = list(_BLOCK.finditer(text))
    for i, mk in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        entries[mk.group(3)] = {"kind": mk.group(1), "at": mk.group(2), "text": text[mk.end():end].strip()}
    return (m.group(1) if m else None), entries


def _norm(s):
    s = s.strip().strip("…").strip()
    s = re.sub(r"^\.{3}|\.{3}$", "", s).strip()
    return re.sub(r"\s+", " ", s)


def quote_found(quote, entry_text):
    q = _norm(quote)
    return bool(q) and q in _norm(entry_text)


def before(at, raised):
    """True when the time `at` is surely before an item was raised. A raised_at without a time is a local date
    of unknown zone, so it counts from the earliest moment that date starts anywhere (UTC+14)."""
    start = instant(raised)
    if "T" not in raised:
        start -= datetime.timedelta(hours=14)
    return instant(at) < start


def check(ext, digest_text, known=None, others=None):
    """Return a list of problems; empty means the output can be appended. others maps the 8-character ids of the
    sessions this run was asked to summarize (see treesight.py prepare) to their full id."""
    probs = Validator().validate(ext, "extract.schema.json")
    if probs:
        return probs
    seen_others = set()
    for i, o in enumerate(ext.get("others", [])):
        if o["session"] not in (others or {}):
            probs.append("others[%d]: %s is not one of the sessions show others listed" % (i, o["session"]))
        elif o["session"] in seen_others:
            probs.append("others[%d]: %s is summarized twice" % (i, o["session"]))
        seen_others.add(o["session"])
    session, entries = parse_digest(digest_text)
    known = known or {"nodes": [], "open": []}
    if ext["session"] != session:
        probs.append("session %s is not the digest's %s" % (ext["session"], session))
    if entries and ext["through"] != list(entries)[-1]:
        probs.append("through is not the last entry of the digest")

    def cites(where, msg, at, ev):
        if msg not in entries:
            probs.append("%s: msg %s is not an entry of the digest" % (where, msg))
        elif entries[msg]["at"] != at:
            probs.append("%s: at %s is not that entry's time %s" % (where, at, entries[msg]["at"]))
        for j, e in enumerate(ev):
            w = "%s.evidence[%d]" % (where, j)
            if e["msg"] not in entries:
                probs.append("%s: msg is not an entry of the digest" % w)
                continue
            ent = entries[e["msg"]]
            if e["kind"] != ent["kind"]:
                probs.append("%s: kind %s, the entry is %s" % (w, e["kind"], ent["kind"]))
            if e["at"] != ent["at"]:
                probs.append("%s: at is not the entry's time" % w)
            if not quote_found(e["quote"], ent["text"]):
                probs.append("%s: quote not found in the entry: %r" % (w, e["quote"][:80]))

    node_ids = {n["id"] for n in known.get("nodes", [])}
    raised = {o["id"]: o.get("raised_at") for o in known.get("open", [])}
    open_ids = set(raised)
    refs = [n["ref"] for n in ext["nodes"]] + [o["ref"] for o in ext["open"]]
    if len(refs) != len(set(refs)):
        probs.append("refs repeat")
    new_nodes = {n["ref"] for n in ext["nodes"]}
    new_open = {o["ref"] for o in ext["open"]}
    for i, n in enumerate(ext["nodes"]):
        cites("nodes[%d]" % i, n["msg"], n["at"], n["evidence"])
        for j, e in enumerate(n["evidence"]):
            if "twig" in e and e["twig"] >= len(n.get("twigs") or []):
                probs.append("nodes[%d].evidence[%d].twig %d: the node has %d twig(s)" % (i, j, e["twig"], len(n.get("twigs") or [])))
        ov = n.get("overturns")
        if ov and ov not in node_ids | new_nodes:
            probs.append("nodes[%d].overturns %s is neither in the ledger nor in this output" % (i, ov))
        if ov == n["ref"]:
            probs.append("nodes[%d] overturns itself" % i)
    for i, o in enumerate(ext["open"]):
        cites("open[%d]" % i, o["msg"], o["raised_at"], o["evidence"])
        b = o.get("blocked_by")
        if b and b not in open_ids | new_open:
            probs.append("open[%d].blocked_by %s is neither in the ledger nor in this output" % (i, b))
        if o["kind"] != "wait" and o.get("who"):
            probs.append("open[%d]: who is only for wait" % i)
    for i, c in enumerate(ext["close"]):
        if c["id"] not in open_ids:
            probs.append("close[%d]: %s is not an open item in the ledger" % (i, c["id"]))
        if c["msg"] not in entries:
            probs.append("close[%d]: msg is not an entry of the digest" % i)
            continue
        ent = entries[c["msg"]]
        if c["at"] != ent["at"]:
            probs.append("close[%d]: at %s is not that entry's time %s" % (i, c["at"], ent["at"]))
        if not quote_found(c["quote"], ent["text"]):
            probs.append("close[%d]: quote not found in the entry" % i)
        if raised.get(c["id"]) and before(ent["at"], raised[c["id"]]):
            probs.append("close[%d]: the quote is from before %s was raised, so it cannot settle it" % (i, c["id"]))
    # settled: an item opened here that a session drawn earlier but later in time already settled; only the later
    # records the digest's header listed may be named, and the ledger copies the quote from the record itself
    listed = set(re.findall(r"(?m)^  later (\S+) ", digest_text.split("\n\n---\n\n", 1)[0]))
    later = {r["id"]: r for r in known.get("later", [])}
    raised_new = {o["ref"]: o["raised_at"] for o in ext["open"]}
    seen = set()
    for i, s in enumerate(ext.get("settled", [])):
        if s["ref"] not in raised_new:
            probs.append("settled[%d]: %s is not an open item of this output" % (i, s["ref"]))
        elif s["ref"] in seen:
            probs.append("settled[%d]: %s is settled twice" % (i, s["ref"]))
        seen.add(s["ref"])
        if s["by"] not in listed:
            probs.append("settled[%d]: %s is not one of the later records in the digest's header" % (i, s["by"]))
        elif s["by"] not in later:
            probs.append("settled[%d]: %s is no longer in the ledger" % (i, s["by"]))
        elif s["ref"] in raised_new and before(later[s["by"]]["at"], raised_new[s["ref"]]):
            probs.append("settled[%d]: %s is from before %s was raised, so it cannot settle it" % (i, s["by"], s["ref"]))
    return probs


# ---------- storage ----------
def home():
    if os.environ.get("TREESIGHT_HOME"):
        return os.environ["TREESIGHT_HOME"]
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "treesight")


def project_key(value):
    """A project key from a key, a transcript folder, or a transcript file."""
    value = os.path.expanduser(value)
    if os.sep in value:
        path = os.path.abspath(value)
        return os.path.basename(os.path.dirname(path) if path.endswith(".jsonl") else path.rstrip(os.sep))
    return value


def project_dir(key):
    if not key or "/" in key or key in (".", ".."):
        raise ValueError("bad project key %r" % key)
    return os.path.join(home(), "projects", key)


def private_dir(path):
    """Make a folder only the user can read: the ledger and work files hold text from sessions. Only a folder made
    here is restricted; one that already exists keeps its mode, so a wrong path passed in is never changed."""
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
        os.chmod(path, 0o700)
    return path


def write_private(path, text):
    """Write a file only the user can read, replacing it in one step so a reader never sees half of it."""
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


@contextlib.contextmanager
def project_lock(key):
    """Held while reading the ledger, checking an extraction or an edit, and appending it, so two runs at the
    same time cannot both number their items from the same state."""
    private_dir(home())
    private_dir(os.path.join(home(), "projects"))
    d = private_dir(project_dir(key))
    fd = os.open(os.path.join(d, ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if fcntl:
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if fcntl:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read(path):
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    raise ValueError("%s line %d is not JSON; the file was edited by hand or cut short" % (path, n))
    return out


def _append(path, events):
    private_dir(os.path.dirname(path))
    data = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    os.chmod(path, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        if fcntl:
            fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        finally:
            if fcntl:
                fcntl.flock(f, fcntl.LOCK_UN)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- rebuilding the current state ----------
def view(events, edits=()):
    """Fold the ledger, then the user's edits, into {"sessions": {id: {...}}, "open": [...], "closed": [...]}.

    An open item is open until a close: a sure close as done removes it, an unsure one marks it
    "confirm", an expired one marks it "stale". The user's edits come last and always win.
    "closes" keeps the model's closes that took effect and that the user has not undone, with their quotes:
    they are evidence a session drawn later can be shown (see known_for)."""
    sessions, items, closed = {}, {}, {}
    order, closes = [], []
    for e in events:
        sid = e.get("session")
        s = sessions.setdefault(sid, {"through": None, "runs": 0, "nodes": [], "last_run": None, "meta": None, "gist": None}) if sid else None
        ev = e.get("ev")
        this_run = s is not None and s["last_run"] and e.get("run") in s["last_run"]["ids"]
        if ev == "run":
            s["through"], s["runs"] = e["through"], s["runs"] + 1
            # a later pass of the same run (prepare --continue) adds to it: the page counts what the whole run did, as
            # the report does, and keeps what every pass was unsure about
            lr = s["last_run"] if e.get("pass", 1) > 1 and s["last_run"] else None
            notes = "\n\n".join(x.strip() for x in ((lr or {}).get("notes"), e.get("notes")) if x and x.strip())
            s["last_run"] = {"id": e["run"], "ids": (lr["ids"] if lr else []) + [e["run"]], "at": e["at"],
                             "nodes": lr["nodes"] if lr else 0, "open": lr["open"] if lr else 0, "closed": 0, "flagged": 0,
                             "_closes": lr["_closes"] if lr else [], "notes": notes or None}
            s["meta"] = e.get("session_meta") or s["meta"]
            if e.get("gist"):       # the run's own one-sentence summary, from reading the whole session
                s["gist"] = {"text": e["gist"], "upto": (e.get("session_meta") or {}).get("last_at"), "at": e["at"]}
        elif ev == "gist":          # a summary another session's run wrote from a short excerpt of this one
            s["gist"] = {"text": e["gist"], "upto": e.get("upto"), "at": e["at"]}
        elif this_run and ev in ("node", "open"):
            s["last_run"]["nodes" if ev == "node" else "open"] += 1
        if ev == "node":
            s["nodes"].append(dict(e["node"]))
        elif ev == "open":
            items[e["item"]["id"]] = dict(e["item"], state="open", session=sid)
            order.append(e["item"]["id"])
        elif ev == "close":
            c = e["close"]
            it = items.get(c["id"])
            if it is None or c["id"] in closed:
                continue
            if c["status"] == "done" and c["sure"]:
                closed[c["id"]] = dict(c, by="model")
            else:
                it["state"] = "confirm" if c["status"] == "done" else "stale"
            closes.append(dict(c, session=sid))
            if this_run:
                s["last_run"]["_closes"].append(c["id"])
    hidden = set()
    for e in edits:
        ev, t = e.get("ev"), e.get("target")
        if ev == "close" and t in items:
            closed[t] = {"id": t, "status": e.get("status", "done"), "by": "user", "at": e["at"]}
        elif ev == "reopen" and t in items:
            closed.pop(t, None)
            items[t]["state"] = "open"
            closes = [c for c in closes if c["id"] != t]     # the user said the model's close was wrong
        elif ev == "hide":
            hidden.add(t)
        elif ev == "set":
            target = items.get(t) or next((n for s in sessions.values() for n in s["nodes"] if n["id"] == t), None)
            if target is not None:
                for k, v in e["fields"].items():
                    if v in ("", None) and k in CLEARABLE:
                        target.pop(k, None)      # "due=" removes the due date
                    else:
                        target[k] = v
    for s in sessions.values():
        s["nodes"] = [n for n in s["nodes"] if n["id"] not in hidden]
        lr = s["last_run"]
        for i in dict.fromkeys((lr or {}).pop("_closes", [])):
            # what the run's closes come to now: closed, or still listed for the user to confirm; a close the user's
            # own reopen, close or hide overrides counts as neither, so these numbers match the page
            if i in closed and closed[i]["by"] == "model":
                lr["closed"] += 1
            elif i not in closed and i not in hidden and items[i]["state"] in ("confirm", "stale"):
                lr["flagged"] += 1
    closes = [c for c in closes if c["id"] not in hidden]
    return {"sessions": sessions,
            "open": [items[i] for i in order if i not in closed and i not in hidden],
            "closed": [dict(closed[i], label=items[i]["label"], session=items[i]["session"]) for i in order if i in closed],
            "closes": [dict(c, label=items[c["id"]]["label"]) for c in closes]}


def load(key):
    d = project_dir(key)
    return view(_read(os.path.join(d, "ledger.jsonl")), _read(os.path.join(d, "edits.jsonl")))


def known_for(state, session):
    """What the extraction of one session is told the ledger already holds: that session's nodes and
    every item still open anywhere in the project, so a later session can close an earlier one's.

    "later" is what other sessions recorded, each with one quote and its time: their nodes, and the model's closes
    made in them. A session drawn after sessions that came later in time is shown the records from after its digest
    starts (transcript.digest_pass picks them), because those sessions could not close the items it is about to open."""
    s = state["sessions"].get(session) or {"nodes": []}
    later = []
    for sid, other in state["sessions"].items():
        if sid == session:
            continue
        for n in other["nodes"]:
            if not n.get("evidence"):
                continue
            ev = n["evidence"][0]
            later.append({"id": n["id"], "what": n["kind"], "label": n["label"], "line": n.get("line"),
                          "quote": ev["quote"], "msg": ev["msg"], "at": ev["at"]})
    closes = {c["id"]: c for c in state.get("closes", []) if c["session"] != session}    # an item's last close
    for c in closes.values():
        later.append({"id": c["id"], "what": "closed: " + c["status"], "label": c["label"], "line": None,
                      "quote": c["quote"], "msg": c["msg"], "at": c["at"]})
    return {"nodes": [{k: n[k] for k in ("id", "kind", "label")} for n in s["nodes"]],
            "open": [{k: o[k] for k in ("id", "kind", "label", "line", "raised_at")} for o in state["open"]],
            "later": sorted(later, key=lambda r: r["at"])}


# ---------- writing ----------
def _next_numbers(events, prefix):
    hi = {"n": 0, "o": 0}
    ids = [e["node"]["id"] for e in events if e.get("ev") == "node"] + [e["item"]["id"] for e in events if e.get("ev") == "open"]
    for i in ids:
        m = re.match(r"^%s-([no])(\d+)$" % prefix, i)
        if m:
            hi[m.group(1)] = max(hi[m.group(1)], int(m.group(2)))
    return hi


# what the page needs to keep showing a session after Claude Code has deleted its transcript
SESSION_META = ("title", "custom_title", "first_at", "last_at", "prompts", "compactions", "summary", "cwd")


def _own_first(x):
    """Its evidence with the quotes from its own message first: the first quote is the one later sessions are shown
    (known_for), and the message a node or item comes from is where its outcome or request is stated."""
    return sorted(x["evidence"], key=lambda e: e["msg"] != x["msg"])


def apply(ext, digest_text, key, model=None, meta=None, pass_number=1, others=None):
    """Check an extraction output and append it. Returns (problems, summary); nothing is written when there are problems.

    meta is the session's metadata as its transcript has it now (see SESSION_META); it is stored with the run.
    pass_number above 1 marks a later pass of the run before it, so the two count as one run (see view).
    others maps the 8-character ids of the other sessions this run may summarize to {"id", "upto"}.
    The whole read, check and append happens under the project lock."""
    with project_lock(key):
        return _apply(ext, digest_text, key, model, meta, pass_number, others or {})


def _apply(ext, digest_text, key, model, meta, pass_number, others):
    d = project_dir(key)
    events, edits = _read(os.path.join(d, "ledger.jsonl")), _read(os.path.join(d, "edits.jsonl"))
    state = view(events, edits)
    known = known_for(state, ext["session"]) if isinstance(ext, dict) and "session" in ext else None
    probs = check(ext, digest_text, known, others)
    prev = (state["sessions"].get(ext.get("session")) or {}).get("through") if isinstance(ext, dict) else None
    if not probs and prev and prev in parse_digest(digest_text)[1]:
        probs.append("the digest repeats entries the ledger already read; build it with --after %s" % prev)
    start = re.search(r"^range: .*?(?:, continuing after (\S+))?$", digest_text, re.M)
    if not probs and start and start.group(1) != prev:    # two runs of one session: only the first to apply is recorded
        probs.append("another run recorded this session since this digest was made; nothing from this run was recorded")
    if probs:
        return probs, None
    sid, p8 = ext["session"], ext["session"][:8]
    hi = _next_numbers(events, p8)
    ids = {}
    for n in ext["nodes"]:
        hi["n"] += 1
        ids[n["ref"]] = "%s-n%d" % (p8, hi["n"])
    for o in ext["open"]:
        hi["o"] += 1
        ids[o["ref"]] = "%s-o%d" % (p8, hi["o"])
    run, at = uuid.uuid4().hex[:12], _now()
    base = {"v": 1, "at": at, "run": run, "session": sid}
    run_ev = dict(base, ev="run", through=ext["through"], after=(state["sessions"].get(sid) or {}).get("through"),
                  rules=ext["schema"], model=model, notes=ext.get("notes"))
    if pass_number > 1:
        run_ev["pass"] = pass_number
    if meta:
        run_ev["session_meta"] = {k: meta[k] for k in SESSION_META if k in meta}
    if ext.get("gist"):
        run_ev["gist"] = ext["gist"]
    out = [run_ev]
    for n in ext["nodes"]:
        node = {k: v for k, v in n.items() if k != "ref"}
        node.update(id=ids[n["ref"]], by="model", evidence=_own_first(n))
        if "overturns" in n:
            node["overturns"] = ids.get(n["overturns"], n["overturns"])
        out.append(dict(base, ev="node", node=node))
    for o in ext["open"]:
        item = {k: v for k, v in o.items() if k != "ref"}
        item.update(id=ids[o["ref"]], by="model", evidence=[{k: v for k, v in e.items() if k != "twig"} for e in _own_first(o)])
        if "blocked_by" in o:
            item["blocked_by"] = ids.get(o["blocked_by"], o["blocked_by"])
        out.append(dict(base, ev="open", item=item))
    for c in ext["close"]:
        out.append(dict(base, ev="close", close=c))
    later = {r["id"]: r for r in known["later"]}
    for s in ext.get("settled", []):      # a close of a new item, with the later record's own quote
        r = later[s["by"]]
        out.append(dict(base, ev="close", close={"id": ids[s["ref"]], "status": s["status"], "sure": s["sure"],
                                                 "quote": r["quote"], "msg": r["msg"], "at": r["at"], "via": s["by"]}))
    for o in ext.get("others", []):
        other = others[o["session"]]
        out.append(dict(base, ev="gist", session=other["id"], gist=o["gist"], upto=other["upto"]))
    _append(os.path.join(d, "ledger.jsonl"), out)
    after = view(events + out, edits)
    lr = after["sessions"][sid]["last_run"]
    # nodes, open, closed and to_confirm count the whole run so far (all its passes, as the page does); close and
    # settled count what this pass proposed
    return [], {"run": run, "nodes": lr["nodes"], "open": lr["open"], "close": len(ext["close"]),
                "settled": len(ext.get("settled", [])), "closed": lr["closed"], "to_confirm": lr["flagged"],
                "open_in_project": len(after["open"]), "summaries": len(ext.get("others", [])) + bool(ext.get("gist")), "ids": ids}


_SET_FIELDS = ("label", "line", "kind", "due", "when", "who", "rank", "score", "blocked_by")
CLEARABLE = ("due", "when", "who", "rank", "score", "blocked_by")
# reopen undoes a close, and also the model's unsure close or "no longer possible" mark on an item still listed
_ACTS_ON = {"close": ("open item",), "reopen": ("closed item", "item to confirm"), "hide": ("open item", "node"),
            "set": ("open item", "node")}


def _edited_problems(obj, what, sid, state, fields):
    """Problems of a node or an open item once the user's change is applied; the page would fail to build with them."""
    body = {k: v for k, v in obj.items() if k != "session"}
    doc = {"schema": "treesight/session@1", "id": sid, "title": "t", "first_at": "2026-01-01T00:00:00Z",
           "last_at": "2026-01-01T00:00:00Z", "prompts": {"total": 0, "substantive": 0}, "generated": True,
           "nodes": [body] if what == "node" else [], "open": [body] if what == "open item" else []}
    probs = [p.split(": ", 1)[-1] if p.startswith("$.") else p for p in Validator().validate(doc, "session.schema.json")]
    if what == "open item":
        if body.get("who") and body.get("kind") != "wait":
            probs.append("who is only for items that wait (kind=wait)")
        b = fields.get("blocked_by")       # only a new one is checked; an older one may point to an item closed since
        if b and (b == body["id"] or b not in {o["id"] for o in state["open"]}):
            probs.append("blocked_by must be the id of another open item")
    return probs


def _a(what):
    return ("an " if what[0] in "aeiou" else "a ") + what


def edit(key, action, target, fields=None):
    """Record one of the user's own changes, after checking that it applies to the target and leaves it valid."""
    with project_lock(key):
        d = project_dir(key)
        events, edits = _read(os.path.join(d, "ledger.jsonl")), _read(os.path.join(d, "edits.jsonl"))
        state = view(events, edits)
        items = {o["id"]: o for o in state["open"]}
        closed = {c["id"] for c in state["closed"]}
        nodes = {n["id"]: sid for sid, s in state["sessions"].items() for n in s["nodes"]}
        what = "closed item" if target in closed else "node" if target in nodes else None
        if target in items:
            what = "item to confirm" if action == "reopen" and items[target]["state"] in ("confirm", "stale") else "open item"
        if what is None:
            raise ValueError("no item or node %s in this project" % target)
        if what not in _ACTS_ON[action]:
            raise ValueError("%s works on %s; %s is %s" % (action, " or ".join(_a(w) for w in _ACTS_ON[action]), target, _a(what)))
        e = {"v": 1, "at": _now(), "ev": action, "target": target}
        if action == "set":
            bad = set(fields or {}) - set(_SET_FIELDS)
            if bad or not fields:
                raise ValueError("cannot set %s; fields are %s" % (sorted(bad) or "nothing", ", ".join(_SET_FIELDS)))
            e["fields"] = fields
            after = view(events, edits + [e])
            if what == "open item":
                obj, sid = next(o for o in after["open"] if o["id"] == target), items[target]["session"]
            else:
                sid = nodes[target]
                obj = next(n for n in after["sessions"][sid]["nodes"] if n["id"] == target)
            probs = _edited_problems(obj, what, sid, after, fields)
            if probs:
                raise ValueError("not changed, %s would not be valid: %s" % (target, "; ".join(probs[:5])))
        _append(os.path.join(d, "edits.jsonl"), [e])
        return e


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "apply"):
        c = sub.add_parser(name)
        c.add_argument("extract")
        c.add_argument("digest")
        c.add_argument("--project", required=(name == "apply"))
        c.add_argument("--model")
    v = sub.add_parser("view")
    v.add_argument("--project", required=True)
    e = sub.add_parser("edit")
    e.add_argument("--project", required=True)
    e.add_argument("action", choices=["close", "reopen", "hide", "set"])
    e.add_argument("target")
    e.add_argument("fields", nargs="*", help="FIELD=VALUE, for set")
    a = ap.parse_args(argv)
    if getattr(a, "project", None):
        a.project = project_key(a.project)
    if a.cmd == "view":
        json.dump(load(a.project), sys.stdout, ensure_ascii=False, indent=1)
        print()
        return 0
    if a.cmd == "edit":
        fields = {}
        for f in a.fields:
            if "=" not in f:
                raise SystemExit("--field %r: expected FIELD=VALUE" % f)
            k, v = f.split("=", 1)
            fields[k.strip()] = v.strip()
        for k in ("rank", "score"):
            if fields.get(k):       # an empty value clears the field, as in treesight.py
                if not re.fullmatch(r"-?\d+", fields[k]):
                    raise SystemExit("%s must be a whole number, not %r" % (k, fields[k]))
                fields[k] = int(fields[k])
        print(json.dumps(edit(a.project, a.action, a.target, fields), ensure_ascii=False))
        return 0
    with open(a.extract, encoding="utf-8") as f:
        ext = json.load(f)
    with open(a.digest, encoding="utf-8") as f:
        dig = f.read()
    if a.cmd == "check":
        known = known_for(load(a.project), ext.get("session")) if a.project else None
        probs = check(ext, dig, known)
        summary = None
    else:
        probs, summary = apply(ext, dig, a.project, a.model)
    for p in probs:
        print(p)
    if summary:
        print(json.dumps(summary, ensure_ascii=False))
    print("ok" if not probs else "%d problem(s), nothing written" % len(probs), file=sys.stderr)
    return 1 if probs else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        sys.exit(1)

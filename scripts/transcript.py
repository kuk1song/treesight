#!/usr/bin/env python3
"""Read a Claude Code session transcript (~/.claude/projects/<project>/<session>.jsonl).

The transcript format is internal to Claude Code and may change in any release, so every read of it
lives in this file. Everything handed to a model goes through scrub(): common secret formats are
removed, IPv4 addresses and email addresses are masked.

treesight's own traces are left out: the /treesight command itself and the main conversation's turn that
its completion notice starts. They are not part of what the session was about, and counting them would make
every run in the current session find "new" content.

Usage:
  python3 transcript.py meta   <session.jsonl>
  python3 transcript.py digest <session.jsonl> [--after MSG_UUID] [--until TIME] [--known KNOWN.json] [--max-chars N]
"""
import argparse
import datetime
import json
import re
import sys

# ---------- scrubbing ----------
_SECRETS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{20,}"),                      # OpenAI, Anthropic and similar API keys
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"),             # Stripe secret and restricted keys
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"),                             # GitLab personal access token
    re.compile(r"\bnpm_[A-Za-z0-9]{36}\b"),                                # npm access token
    re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),                                # Hugging Face token
    re.compile(r"\bya29\.[A-Za-z0-9_-]{20,}"),                             # Google OAuth access token
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),                        # Slack
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),                          # AWS access key id
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),                              # Google API key
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),   # JWT
    re.compile(r"\bgsk_[A-Za-z0-9]{40,}"),                                # Groq
    re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{20,}"),                            # Google OAuth client secret
    re.compile(r"\bwhsec_[A-Za-z0-9+/=]{20,}"),                            # Stripe webhook signing secret
    re.compile(r"\bxapp-\d-[A-Za-z0-9-]{10,}"),                             # Slack app-level token
    re.compile(r"\bshp(?:at|ca|pa|ss)_[A-Fa-f0-9]{32}\b"),                 # Shopify access token
    re.compile(r"\bhttps://hooks\.slack\.com/(?:services|workflows|triggers)/[A-Za-z0-9/_-]+"),     # Slack webhook
    re.compile(r"\bhttps://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]+"),   # Discord webhook
    re.compile(r"(?i)\bAccountKey=[A-Za-z0-9+/]{20,}={0,2}"),               # Azure storage connection string
    re.compile(r"(?i)(?<![\w-])--(?:password|passwd|passphrase|token|secret|api-key)\s+(?!-)[^\s'\"]{6,}"),   # --password hunter2
    re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"),            # SendGrid
    re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{33}(?![A-Za-z0-9_-])"),       # Telegram bot token (it may end in -)
    # Discord bot token: the user id in base64 (M, N or O first), a time and an HMAC; a digit somewhere in the token
    # keeps out dotted names such as ModelSerializerFactoryImpl.create.serialize..., and the bound keeps the look ahead
    # linear on long runs of letters and dots
    re.compile(r"\b(?=[MNO][A-Za-z0-9._-]{0,80}\d)[MNO][A-Za-z0-9]{23,25}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}"),
    # a name with token, password, secret or api key in it (DB_PASSWORD, client_secret, "password" in JSON), then a value
    # that is not just a number (max_tokens: 4096 and password_changed_at: 1729500000 stay); at most 100 name characters
    # after the word, which keeps a long run of such words linear
    re.compile(r"(?i)\b[a-z0-9_]*(?:token|password|passwd|passphrase|secret|api[_-]?key)[a-z0-9_]{0,100}['\"]?\s*[:=]\s*['\"]?(?![0-9]+\b)[^\s'\"]{8,}"),
    # a name that ends in password, then a value of digits only (DB_PASSWORD=12345678)
    re.compile(r"(?i)\b[a-z0-9_]*(?:password|passwd|passphrase)['\"]?\s*[:=]\s*['\"]?[0-9]{6,}\b"),
    # any other name ending in _key (OPENAI_KEY, ACCESS_KEY), when the value looks like a key: 16 or more letters and
    # digits, both present, not followed by a dot or a slash, so routing_key = "orders.created.v1", s3_key paths and
    # file names stay (values over 512 characters are left: the bound keeps a long run of such names linear)
    re.compile(r"(?i)\b[a-z0-9]+(?:_[a-z0-9]+)*_key['\"]?\s*[:=]\s*['\"]?(?=[A-Za-z0-9_+=-]{0,512}\d)(?=[A-Za-z0-9_+=-]{0,512}[a-z])[A-Za-z0-9_+=-]{16,512}(?![A-Za-z0-9_+=./-])"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"(?i)\bauthorization:\s*basic\s+[A-Za-z0-9+/]{8,}={0,2}"),   # HTTP basic credentials
    re.compile(r"\b[a-z][a-z0-9+.-]{0,31}://[^\s/:@]+:[^\s/@]+@"),         # credentials inside a URL (a scheme is short;
                                                                           # the bound keeps long dotted runs linear)
    re.compile(r"\b(?:vless|vmess|trojan|ss|ssr|hysteria2?|tuic)://\S+"),  # proxy share links
]
_IPV4 = re.compile(r"(?<![\d.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\d.]*\d)")
# starting only where a run of address characters starts: the same matches, in linear time on a long run without @
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}")


def scrub(text):
    for rx in _SECRETS:
        text = rx.sub("[secret]", text)
    masked = None
    while masked != text:       # again after a mask: an address right after another starts a new run there
        masked, text = text, _EMAIL.sub("[email]", text)
    return _IPV4.sub("x.x.x.x", text)


# ---------- reading ----------
def records(path):
    """Every JSON record in the file; a damaged line is skipped, not fatal."""
    with open(path, encoding="utf-8", errors="replace") as f:     # a line Claude Code is still writing may end mid-character
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


def _text_blocks(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") == "text")
    return ""


def _has_tool_result(content):
    return isinstance(content, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in content)


_WRAPPERS = ("<command-name>", "<command-message>", "<local-command-", "<bash-input>", "<bash-stdout>", "<bash-stderr>",
             "<task-notification>", "<system-reminder>", "Caveat:", "<user-prompt-submit-hook>", "[Request interrupted by user")


# Claude Code 2.1.299 records a forked skill's command as the plain text the user typed ("/treesight:treesight
# words"), and its completion as a task notification whose summary names the command.
_OWN_COMMAND = re.compile(r"^/(?:treesight:)?treesight(?:\s|$)")
_OWN_NOTICE = re.compile(r'<summary>Agent "/(?:treesight:)?treesight[\s"]')


def is_prompt(rec):
    """A message the user typed (or queued) themselves; the /treesight command is not one."""
    if rec.get("type") != "user" or rec.get("isMeta") or rec.get("isCompactSummary") or rec.get("isSidechain"):
        return False
    origin = rec.get("origin")
    if isinstance(origin, dict) and origin.get("kind") != "human":
        return False
    content = (rec.get("message") or {}).get("content")
    if _has_tool_result(content):
        return False
    text = _text_blocks(content).lstrip()
    return bool(text) and not text.startswith(_WRAPPERS) and not _OWN_COMMAND.match(text)


def starts_turn(rec):
    """A user record that begins a turn: a prompt, a slash command, a notice from another agent, a shell
    command; not a tool result, a reminder or a compaction summary, which belong to the turn under way."""
    if rec.get("type") != "user" or rec.get("isMeta") or rec.get("isCompactSummary") or rec.get("isSidechain"):
        return False
    return not _has_tool_result((rec.get("message") or {}).get("content"))


def is_own_trace(rec):
    """The /treesight command, or the notice that a treesight run finished: what follows until the user's next
    prompt is the main conversation reacting to treesight, not the session's own work."""
    if rec.get("type") != "user" or rec.get("isMeta") or rec.get("isSidechain"):
        return False
    text = _text_blocks((rec.get("message") or {}).get("content"))
    origin = rec.get("origin") if isinstance(rec.get("origin"), dict) else {}
    if origin.get("kind") == "task-notification":
        return bool(_OWN_NOTICE.search(text))
    return bool(_OWN_COMMAND.match(text.lstrip()))


_PASTED = re.compile(r"<pasted_content[^>]*>(.*?)</pasted_content[^>]*>", re.S)
_FILLER = {"继续", "断了", "断了,继续", "断了，继续", "go on", "continue", "go", "ok", "好", "好的", "嗯"}


def is_substantive(text):
    """Not just a nudge: at least 6 characters once pasted content and images are taken out, and not a filler word."""
    body = _PASTED.sub("", text)
    body = re.sub(r"\[Image #\d+\]", "", body).strip()
    return len(body) >= 6 and body.lower().strip(" .。!！") not in _FILLER


def _short_paste(text, keep=400):
    def cut(m):
        inner = m.group(1).strip()
        more = len(inner) - keep
        return "[pasted] " + inner[:keep] + (" ...[%d more characters pasted]" % more if more > 0 else "") + " [/pasted]"
    return _PASTED.sub(cut, text)


def scrub_prompt(text):
    """scrub() for a prompt: the text around pasted blocks and each block's content separately, so a value pattern can
    never run into a block's closing tag and swallow the rest of the prompt."""
    out, last = [], 0
    for m in _PASTED.finditer(text):
        out += [scrub(text[last:m.start()]), text[m.start():m.start(1)], scrub(m.group(1)), text[m.end(1):m.end()]]
        last = m.end()
    return "".join(out) + scrub(text[last:])


def session_line(meta, entries):
    """One line about a session for the page: Claude Code's own recap of it, else its first prompt that is not pasted
    output, with pasted text shortened. Scrubbed before anything is cut, since a secret cut in half no longer matches its pattern."""
    if meta["summary"]:
        return scrub(meta["summary"])
    prompts = [e["text"] for e in entries if e["k"] == "P"]
    # a prompt that starts with Claude Code's reply marker is output pasted from another session, not this one's request
    first = next((t for t in prompts if not t.lstrip().startswith("\u23fa")), prompts[0] if prompts else "")
    return _short_paste(scrub_prompt(first), 120)


# compaction summaries: drop the sections that repeat the prompts or dump code; when the rest is still too long,
# shorten sections in reverse order of how much they say about what is open, so Pending Tasks is the last to be cut
_DROP_SECTIONS = ("Files and Code Sections", "All user messages")
_KEEP_FIRST = ("Pending Tasks", "Current Work", "Primary Request", "Errors and fixes", "Problem Solving", "Optional Next Step")


def _trim_compact(text, limit):
    text = re.sub(r"^This session is being continued from a previous conversation.*?\n\n", "", text, flags=re.S)
    parts = [p for p in re.split(r"(?m)^(?=\d+\. [A-Z][A-Za-z ]+:?\s*$)", text) if p.strip()]
    title = lambda p: p.lstrip().split("\n", 1)[0].strip(" 0123456789.:")
    parts = [p for p in parts if not any(title(p).startswith(s) for s in _DROP_SECTIONS)]
    rank = lambda p: next((i for i, s in enumerate(_KEEP_FIRST) if title(p).startswith(s)), len(_KEEP_FIRST))
    room, size = limit, {}
    for i in sorted(range(len(parts)), key=lambda i: rank(parts[i])):
        size[i] = min(len(parts[i]), max(0, room))
        room -= size[i]
    out = []
    for i, p in enumerate(parts):
        if size[i] >= len(p):
            out.append(p)
        elif size[i] >= 120:
            out.append(p[:size[i]].rstrip() + " ...[cut]\n\n")
        else:
            out.append(p.lstrip().split("\n", 1)[0] + " ...[left out]\n\n")
    return "".join(out).strip()


def read_session(path):
    """Metadata and the ordered entries a digest is built from.

    Entry kinds: P prompt, R assistant text (last=True on the last one of a turn), S automatic recap, C compaction summary.
    Each entry also has pos, the number of its record in the file."""
    meta = {"id": None, "title": None, "custom_title": False, "cwd": None, "first_at": None, "last_at": None,
            "prompts": {"total": 0, "substantive": 0}, "compactions": 0, "summary": None}
    ai_title = custom = None
    entries, turn = [], []
    own = False   # inside a turn that treesight started

    def flush():
        if turn:
            turn[-1]["last"] = True
            entries.extend(turn)
            del turn[:]

    for pos, rec in enumerate(records(path)):
        t = rec.get("type")
        if t == "custom-title" and rec.get("customTitle"):
            custom = rec["customTitle"]
        elif t == "ai-title" and rec.get("aiTitle"):
            ai_title = rec["aiTitle"]
        if rec.get("isSidechain") or "timestamp" not in rec:
            continue
        meta["id"] = meta["id"] or rec.get("sessionId")
        meta["cwd"] = meta["cwd"] or rec.get("cwd")
        at = rec["timestamp"]
        if meta["first_at"] is None or at < meta["first_at"]:
            meta["first_at"] = at
        if meta["last_at"] is None or at > meta["last_at"]:
            meta["last_at"] = at
        msg = rec.get("uuid")
        if t == "system" and rec.get("subtype") == "compact_boundary":
            meta["compactions"] += 1
        elif t == "system" and rec.get("subtype") == "away_summary" and rec.get("content"):
            flush()
            entries.append({"k": "S", "msg": msg, "at": at, "text": rec["content"], "pos": pos})
            meta["summary"] = rec["content"]
        elif t == "user" and rec.get("isCompactSummary"):
            flush()
            entries.append({"k": "C", "msg": msg, "at": at, "text": _text_blocks((rec.get("message") or {}).get("content")), "pos": pos})
        elif is_prompt(rec):
            flush()
            own = False
            text = _text_blocks(rec["message"]["content"])
            meta["prompts"]["total"] += 1
            meta["prompts"]["substantive"] += is_substantive(text)
            entries.append({"k": "P", "msg": msg, "at": at, "text": text, "pos": pos})
        elif is_own_trace(rec):
            flush()
            own = True
        elif starts_turn(rec):
            own = False   # what Claude says next answers something else, even if it is not a prompt
        elif t == "assistant" and not own:
            text = _text_blocks((rec.get("message") or {}).get("content")).strip()
            if text:
                turn.append({"k": "R", "msg": msg, "at": at, "text": text, "last": False, "pos": pos})
    flush()
    meta["title"] = custom or ai_title
    meta["custom_title"] = bool(custom)
    return meta, entries


def entries_after(path, entries, after):
    """The entries after message `after`, the last one the ledger read. It is usually an entry; when it is not
    (an earlier version counted the /treesight command as a prompt), the entries after its record in the file.
    A message that is not in the file at all is an error rather than a reason to read everything again."""
    if not after:
        return entries
    ids = [e["msg"] for e in entries]
    if after in ids:
        return entries[ids.index(after) + 1:]
    for pos, rec in enumerate(records(path)):
        if rec.get("uuid") == after:
            return [e for e in entries if e["pos"] > pos]
    raise ValueError("message %s, where the ledger stopped reading, is not in %s any more" % (after, path))


# ---------- digest for the model ----------
_KIND_NAME = {"P": "prompt", "R": "reply", "S": "recap", "C": "compact"}
PASTE_KEEP = 400      # pasted content: the first characters, then a note of how many more were pasted
COMPACT_LIMIT = 8000  # compaction summaries restate earlier messages, which are all in the digest themselves
PASS_CHARS = 150000   # one digest; a longer stretch of new entries is read in several passes
LATER_CHARS = 40000   # records of sessions drawn earlier but later in time: at most this much of a digest's header
LATER_QUOTE = 200     # each record's quote as shown there; the ledger copies the whole quote from the record
# a line inside an entry that looks like an entry header (a session that quotes a digest) gets a leading space,
# so it cannot be read as an entry of its own; quotes are compared with whitespace collapsed, so they still match
_HEADER_LIKE = re.compile(r"(?m)^(?=\[(?:prompt|reply|recap|compact) \S+ [0-9a-f-]{36}\]$)")


def _pastes_cut(text):
    return sum(1 for m in _PASTED.finditer(text) if len(m.group(1).strip()) > PASTE_KEEP)


def _block(e, limit=None):
    """One entry as the model reads it. Nothing is cut except pasted content and compaction summaries (both
    reported in the header), and an entry longer than a whole pass (limit), which is reported too."""
    # scrubbed before anything is cut: a secret cut in half no longer matches its pattern
    if e["k"] == "P":
        text = _short_paste(scrub_prompt(e["text"].strip()), PASTE_KEEP)
    elif e["k"] == "C":
        text = _trim_compact(scrub(e["text"].strip()), COMPACT_LIMIT)
    else:
        text = scrub(e["text"].strip())
    text = _HEADER_LIKE.sub(" ", text.strip())
    if limit is not None and len(text) > limit:
        text = text[:limit] + " ...[cut: %d more characters not shown]" % (len(text) - limit)
    return "[%s %s %s]\n%s" % (_KIND_NAME[e["k"]], e["at"], e["msg"], text)


def _passes(sizes, kinds, budget):
    """Split entries into passes of at most `budget` characters, breaking between turns (before a prompt) where
    that keeps at least half a pass. Returns (start, end) index pairs; an entry larger than a pass is a pass alone."""
    out, i, n = [], 0, len(sizes)
    while i < n:
        start, size, turn = i, 0, None
        while i < n and (i == start or size + sizes[i] + 2 <= budget):
            if i > start and kinds[i] == "P":
                turn = (i, size)
            size += sizes[i] + 2
            i += 1
        if i < n and kinds[i] != "P" and turn and turn[1] >= budget // 2:
            i = turn[0]
        out.append((start, i))
    return out


def instant(t):
    """A time from the transcript (ISO with zone, any number of decimals) or a bare date (its start, UTC), for comparing."""
    t = t if "T" in t else t + "T00:00:00Z"
    t = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], t.replace("Z", "+00:00"))
    return datetime.datetime.fromisoformat(t)


def _later_lines(later, since):
    """Records of other sessions from after this digest starts (see ledger.known_for), newest kept when they are many.
    Those sessions were drawn before this one, so they never saw the items this digest opens."""
    recent = [r for r in later if since and instant(r["at"]) >= instant(since)]
    lines = []
    for r in reversed(recent):
        text = re.sub(r"\s+", " ", r["label"] + (": " + r["line"] if r.get("line") else "")).strip()
        quote = re.sub(r"\s+", " ", r["quote"]).strip()
        quote = quote if len(quote) <= LATER_QUOTE else quote[:LATER_QUOTE - 1] + "\u2026"
        line = "  later %s [%s] %s %s | quote: %s" % (r["id"], r["what"], r["at"], text, quote)
        if sum(len(x) + 1 for x in lines) + len(line) > LATER_CHARS:
            break
        lines.append(line)
    if not lines:
        return []
    left = len(recent) - len(lines)
    return (["later records (other sessions drawn before this one although they come after this digest starts, so they "
             "could not close what it opens; newest last%s):" % (", %d older ones left out" % left if left else "")]
            + lines[::-1])


def digest_pass(path, after=None, known=None, max_chars=PASS_CHARS, until=None, loaded=None):
    """The digest of the next pass: a header, what the ledger already holds, then one block per entry, in full.
    Returns (text, info); info says how many new entries there are and how many are left for later passes.
    loaded: (meta, entries) from read_session(path), when the caller has them already.

    Quotes in the extraction output must be copied from the entry text here; the ledger checks them against it."""
    meta, entries = loaded or read_session(path)
    entries = entries_after(path, entries, after)
    if until:
        entries = [e for e in entries if e["at"] <= until]
    known_lines = []
    since = entries[0]["at"] if entries else None
    if known:
        known_lines.append("already in the ledger (do not add these again; close open ones only by id):")
        for nd in known.get("nodes", []):
            known_lines.append("  node %s [%s] %s" % (nd["id"], nd["kind"], nd["label"]))
        for o in known.get("open", []):
            late = o.get("raised_at") and since and instant(o["raised_at"]) > instant(since)    # only when drawn out of order
            known_lines.append("  open %s [%s] %s: %s%s" % (o["id"], o["kind"], o["label"], o["line"],
                                                           " (raised %s, after this digest starts)" % o["raised_at"] if late else ""))
        known_lines += _later_lines(known.get("later", []), since)
    budget = max(max_chars - sum(len(x) + 1 for x in known_lines) - 1200, max_chars // 4)
    blocks = [_block(e) for e in entries]
    passes = _passes([len(b) for b in blocks], [e["k"] for e in entries], budget)
    first = passes[0] if passes else (0, 0)
    mine = entries[first[0]:first[1]]
    body = [_block(e, budget - 200) if len(blocks[first[0] + j]) > budget else blocks[first[0] + j] for j, e in enumerate(mine)]
    cut = sum(1 for j in range(len(mine)) if len(blocks[first[0] + j]) > budget)
    pastes = sum(_pastes_cut(scrub_prompt(e["text"])) for e in mine if e["k"] == "P")
    compacts = sum(1 for e in mine if e["k"] == "C")
    zh = sum(1 for e in mine if e["k"] == "P" and re.search("[一-鿿]", e["text"]))
    np_ = sum(1 for e in mine if e["k"] == "P")
    rest = len(entries) - len(mine)
    shortened = []
    if pastes:
        shortened.append("pasted text in %d place(s) kept to its first %d characters" % (pastes, PASTE_KEEP))
    if compacts:
        shortened.append("%d compaction summar%s kept to at most %d characters, sections that repeat the prompts or list files left out"
                         % (compacts, "y" if compacts == 1 else "ies", COMPACT_LIMIT))
    if cut:
        shortened.append("%d entr%s longer than a whole digest cut, marked [cut]" % (cut, "y" if cut == 1 else "ies"))
    head = [
        "# treesight digest",
        "session: %s" % meta["id"],
        "title: %s%s" % (scrub(meta["title"] or "(none)"), " (named by the user)" if meta["custom_title"] else ""),
        "range: %s to %s, %d entries%s" % (mine[0]["at"] if mine else "-", mine[-1]["at"] if mine else "-", len(mine),
                                           ", continuing after %s" % after if after else ""),
        "pass: %s" % ("every new entry is in this digest" if not rest else
                      "this digest holds the first %d of %d new entries; the other %d come in a later pass, where items open here may be closed"
                      % (len(mine), len(entries), rest)),
        "prompts in this range: %d, of which %d contain Chinese" % (np_, zh),
        "prompts in the whole session: %d, substantive %d; compactions: %d" % (meta["prompts"]["total"], meta["prompts"]["substantive"], meta["compactions"]),
        "texts shortened: %s; everything else is complete" % ("; ".join(shortened) if shortened else "none"),
    ] + known_lines
    text = "\n".join(head) + "\n\n---\n\n" + "\n\n".join(body) + "\n"
    sizes = [sum(len(b) + 2 for b in blocks[a:z]) for a, z in passes]
    return text, {"entries": len(mine), "new_entries": len(entries), "remaining": rest, "passes": len(passes), "pass_chars": sizes}


def digest(path, after=None, known=None, max_chars=PASS_CHARS, until=None):
    """The text of the next pass's digest; see digest_pass."""
    return digest_pass(path, after, known, max_chars, until)[0]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("meta")
    m.add_argument("path")
    d = sub.add_parser("digest")
    d.add_argument("path")
    d.add_argument("--after")
    d.add_argument("--known")
    d.add_argument("--until", help="only entries at or before this ISO time, for tests")
    d.add_argument("--max-chars", type=int, default=PASS_CHARS)
    a = ap.parse_args(argv)
    if a.cmd == "meta":
        meta, _ = read_session(a.path)
        meta["title"] = scrub(meta["title"] or "")
        meta["summary"] = scrub(meta["summary"]) if meta["summary"] else None
        json.dump(meta, sys.stdout, ensure_ascii=False, indent=1)
        print()
    else:
        known = None
        if a.known:
            with open(a.known, encoding="utf-8") as f:
                known = json.load(f)
        sys.stdout.write(digest(a.path, a.after, known, a.max_chars, a.until))
    return 0


if __name__ == "__main__":
    sys.exit(main())

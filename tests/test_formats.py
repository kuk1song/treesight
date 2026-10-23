"""Schemas, the stdlib validator, the transcript adapter and the extraction check. Run: python3 -m unittest discover -s tests"""
import copy
import glob
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import ledger  # noqa: E402
import transcript  # noqa: E402
from schema import Validator, units  # noqa: E402

FIXTURE = glob.glob(os.path.join(ROOT, "fixtures", "projects", "-home-dev-tidepool", "953c0ab1-*.jsonl"))[0]
with open(os.path.join(ROOT, "fixtures", "extract", "tidepool-1.json"), encoding="utf-8") as f:
    EXTRACT = json.load(f)


def write_transcript(turns, sid="11111111-2222-4333-8444-555555555555"):
    """A made-up transcript: turns is a list of (prompt, [replies]); returns its path and the message ids in order."""
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    ids, n = [], 0
    for prompt, replies in turns:
        for kind, text in [("user", prompt)] + [("assistant", r) for r in replies]:
            n += 1
            uid = "%08x-0000-4000-8000-000000000000" % n
            rec = {"type": kind, "uuid": uid, "sessionId": sid, "timestamp": "2026-09-14T09:%02d:%02d.000Z" % (n // 60, n % 60)}
            if kind == "user":
                rec.update(origin={"kind": "human"}, message={"role": "user", "content": text})
            else:
                rec["message"] = {"role": "assistant", "content": [{"type": "text", "text": text}]}
            f.write(json.dumps(rec) + "\n")
            ids.append(uid)
    f.close()
    return f.name, ids


def session_doc():
    """A small valid session document built from the fixture extraction."""
    ext = copy.deepcopy(EXTRACT)
    ids = {n["ref"]: "953c0ab1-n%d" % (i + 1) for i, n in enumerate(ext["nodes"])}
    oids = {o["ref"]: "953c0ab1-o%d" % (i + 1) for i, o in enumerate(ext["open"])}
    nodes = []
    for n in ext["nodes"]:
        x = {k: v for k, v in n.items() if k != "ref"}
        x.update(id=ids[n["ref"]], by="model")
        if "overturns" in n:
            x["overturns"] = ids[n["overturns"]]
        nodes.append(x)
    open_ = []
    for o in ext["open"]:
        x = {k: v for k, v in o.items() if k != "ref"}
        x.update(id=oids[o["ref"]], by="model", state="open")
        if "blocked_by" in o:
            x["blocked_by"] = oids[o["blocked_by"]]
        open_.append(x)
    return {"schema": "treesight/session@1", "id": ext["session"], "title": "t", "first_at": "2026-09-14T09:02:11.000Z",
            "last_at": "2026-09-15T09:48:01.000Z", "prompts": {"total": 15, "substantive": 15}, "generated": True,
            "nodes": nodes, "open": open_}


class Units(unittest.TestCase):
    def test_counts(self):
        cases = {"同事 Docker 登录成功": 7, "2.1.288 升级": 3, "缓存问题就是 rate limit": 8, "ICS export in UTC confirmed": 5,
                 "#4211 要不要补发": 6, "don't panic": 2, "": 0, "主库宕机后已经恢复": 9}
        for text, n in cases.items():
            self.assertEqual(units(text), n, text)


class Schemas(unittest.TestCase):
    v = Validator()

    def test_fixture_extract_is_valid(self):
        self.assertEqual(self.v.validate(EXTRACT, "extract.schema.json"), [])

    def test_session_doc_is_valid(self):
        self.assertEqual(self.v.validate(session_doc(), "session.schema.json"), [])

    def broken(self):
        ex = []
        e = copy.deepcopy(EXTRACT); e["nodes"][0]["kind"] = "decided"; ex.append(("extract", e))
        e = copy.deepcopy(EXTRACT); del e["nodes"][0]["evidence"]; ex.append(("extract", e))
        e = copy.deepcopy(EXTRACT); e["open"][0]["state"] = "open"; ex.append(("extract", e))
        e = copy.deepcopy(EXTRACT); e["close"] = [{"id": "o1", "status": "done", "sure": True, "quote": "q", "msg": EXTRACT["through"], "at": "2026-09-15T09:48:01.000Z"}]; ex.append(("extract", e))
        s = session_doc(); s["nodes"][0]["at"] = "09-14"; ex.append(("session", s))
        s = session_doc(); s["open"][0]["state"] = "closed"; ex.append(("session", s))
        s = session_doc(); del s["nodes"][0]["by"]; ex.append(("session", s))
        s = session_doc(); st = next(n for n in s["nodes"] if "story" in n); st["story"]["steps"].reverse(); ex.append(("session", s))
        s = session_doc(); st = next(n for n in s["nodes"] if "story" in n); st["story"]["steps"].pop(); ex.append(("session", s))
        s = session_doc(); s["nodes"][0]["evidence"][0]["extra"] = 1; ex.append(("session", s))
        return ex

    def test_broken_documents_fail(self):
        for name, doc in self.broken():
            self.assertTrue(self.v.validate(doc, name + ".schema.json"), name)

    def test_label_units(self):
        e = copy.deepcopy(EXTRACT)
        e["nodes"][0]["label"] = "这是一个超过八个字的标签"
        self.assertTrue(any("units" in p for p in self.v.validate(e, "extract.schema.json")))

    def test_unknown_keyword_is_refused(self):
        v = Validator()
        v.files["x.schema.json"] = {"type": "string", "format": "email"}
        with self.assertRaises(ValueError):
            v.validate("a", "x.schema.json")

    def test_agrees_with_jsonschema(self):
        try:
            import jsonschema
            from referencing import Registry, Resource
        except ImportError:
            self.skipTest("jsonschema not installed")
        docs = {}
        for n in ("common", "extract", "session"):
            with open(os.path.join(ROOT, "schema", n + ".schema.json"), encoding="utf-8") as f:
                docs[n] = json.load(f)
            jsonschema.Draft202012Validator.check_schema(docs[n])
        reg = Registry().with_resources([(d["$id"], Resource.from_contents(d)) for d in docs.values()])
        cases = [("extract", EXTRACT), ("session", session_doc())] + self.broken()
        for name, doc in cases:
            lib = list(jsonschema.Draft202012Validator(docs[name], registry=reg).iter_errors(doc))
            mine = self.v.validate(doc, name + ".schema.json")
            self.assertEqual(bool(lib), bool(mine), name)


class Transcript(unittest.TestCase):
    def test_meta(self):
        meta, entries = transcript.read_session(FIXTURE)
        self.assertEqual(meta["prompts"], {"total": 15, "substantive": 15})
        self.assertEqual(meta["compactions"], 1)
        self.assertEqual(meta["title"], "Add ICS export and switch tidepool to the NOAA API")
        self.assertFalse(meta["custom_title"])
        self.assertEqual(meta["first_at"], "2026-09-14T09:02:11.000Z")
        self.assertEqual([e["k"] for e in entries].count("C"), 1)
        self.assertEqual([e["k"] for e in entries].count("S"), 2)

    def test_tool_results_and_wrappers_are_not_prompts(self):
        base = {"type": "user", "message": {"content": "hello there"}, "origin": {"kind": "human"}}
        self.assertTrue(transcript.is_prompt(base))
        for change in ({"isMeta": True}, {"isCompactSummary": True}, {"isSidechain": True}, {"origin": {"kind": "task-notification"}},
                       {"message": {"content": [{"type": "tool_result", "content": "x"}]}},
                       {"message": {"content": "<command-name>/clear</command-name>"}},
                       {"message": {"content": "/treesight:treesight release"}}, {"message": {"content": "/treesight"}},
                       {"message": {"content": "[Request interrupted by user for tool use]"}}):
            self.assertFalse(transcript.is_prompt(dict(base, **change)), change)

    def test_substantive(self):
        self.assertFalse(transcript.is_substantive("继续"))
        self.assertFalse(transcript.is_substantive("go on"))
        self.assertFalse(transcript.is_substantive('<pasted_content id="a">a long paste</pasted_content id="a"> ok'))
        self.assertTrue(transcript.is_substantive("Fix the parser"))

    def test_scrub(self):
        s = transcript.scrub
        self.assertEqual(s("ip 192.0.2.20 and v2.1.288"), "ip x.x.x.x and v2.1.288")   # documentation addresses (RFC 5737, RFC 2606)
        self.assertEqual(s("mail a.b@example.com now"), "mail [email] now")
        self.assertEqual(s("key " + "sk-" + "ant-" + "api03-" + "abcdefghij" * 3), "key [secret]")
        self.assertEqual(s("api_key=abcd1234efgh5678"), "[secret]")
        self.assertEqual(s("secret detection and token budgets"), "secret detection and token budgets")
        self.assertEqual(s("vless://abc@host:443?x=y"), "[secret]")
        # names that only contain the word (environment variables, JSON keys), all made-up values
        for text, want in (("DB_PASSWORD=hunter2hunter2", "[secret]"), ("export ANTHROPIC_API_KEY=abcdefghijk123", "export [secret]"),
                           ("client_secret=abcdefghijk123", "[secret]"), ('"password": "hunter2hunter2"', '"[secret]"'),
                           ("max_tokens: 4096", "max_tokens: 4096"), ("output_tokens: 123456789", "output_tokens: 123456789"),
                           ("password reset email sent", "password reset email sent")):
            self.assertEqual(s(text), want, text)
        # provider formats, built at run time so that no file in the repository holds a string shaped like a real key
        for token in ("sk_" + "live_" + "a1" * 12, "rk_" + "test_" + "b2" * 12, "glpat-" + "c3" * 10, "npm_" + "d4" * 18,
                      "hf_" + "e5" * 16, "ya29." + "f6" * 12, "gsk_" + "a7" * 24, "SG." + "b8" * 11 + "." + "c9" * 21,
                      "1234567890:" + "AA" + "d1" * 16 + "e", "1234567890:" + "AA" + "d1" * 16 + "-",
                      "M" + "a1" * 12 + "." + "b2c3d4" + "." + "e5" * 14, "O" + "a1" * 12 + "." + "b2c3d4" + "." + "e5" * 14,
                      "GOCSPX-" + "f7" * 14, "whsec_" + "g8" * 16, "xapp-1-" + "A0B1C2" * 4, "shpat_" + "ab12" * 8,
                      "https://hooks." + "slack.com/services/" + "T0A1/B2C3/" + "d4e5" * 6,
                      "https://discord" + ".com/api/webhooks/" + "1234567890/" + "h9" * 30,
                      "AccountKey=" + "i0J1" * 11 + "==", "--password " + "hunter2x", "--api-key " + "k1" * 10):
            self.assertEqual(s("token " + token + " end"), "token [secret] end", token)
        # names ending in _key with a key-like value and all-digit passwords; ordinary settings, interface text and paths stay
        for text, want in (("OPENAI_KEY=" + "ab12" * 5, "[secret]"), ("export ACCESS_KEY=" + "cd34" * 5, "export [secret]"),
                           ("DB_PASSWORD=" + "1234" * 3, "[secret]"), ("sort_key=created_at", "sort_key=created_at"),
                           ("primary_key: id", "primary_key: id"), ("MAX_KEY_LEN=12", "MAX_KEY_LEN=12"),
                           ("the time is 12:30 now", "the time is 12:30 now"),
                           ('"forgot_password": "Forgot your password?"', '"forgot_password": "Forgot your password?"'),
                           ("password_changed_at: 1729500000", "password_changed_at: 1729500000"),
                           ("secret_version = 20241021", "secret_version = 20241021"),
                           ('routing_key = "orders.created.v1"', 'routing_key = "orders.created.v1"'),
                           ("ssh_key=/Users/me/.ssh/id_ed25519", "ssh_key=/Users/me/.ssh/id_ed25519"),
                           ("s3_key=uploads2026abcdefgh/photo.jpg", "s3_key=uploads2026abcdefgh/photo.jpg"),
                           ('cache_key = "user_profile_12345.json"', 'cache_key = "user_profile_12345.json"'),
                           ("DB_PASSWORD=ab<cd" + "efgh1234", "[secret]"), ('"password": "Tr0ub<dor&3xyz"', '"[secret]"'),
                           ("mail a@b.co" + "x.y+z@example.org", "mail [email][email]"),
                           ("SPRING_SECURITY_OAUTH2_CLIENT_REGISTRATION_GOOGLE_CLIENT_SECRET=" + "Abc123" * 3, "[secret]"),
                           ("--token-file ~/.config/app/tok", "--token-file ~/.config/app/tok"),
                           ("ModelSerializerFactoryImpl.create.serializeWithCustomOptionsForAll",
                            "ModelSerializerFactoryImpl.create.serializeWithCustomOptionsForAll")):
            self.assertEqual(s(text), want, text)
        self.assertEqual(s("Authorization: Basic " + "dXNlcjpwYXNz" * 2), "[secret]")
        self.assertEqual(s("npm_modules and hf_hub are names, not keys"), "npm_modules and hf_hub are names, not keys")

    def test_scrubbing_takes_linear_time(self):
        """Long runs without spaces (minified code, base64, dotted names) took seconds to minutes: the email, URL,
        Discord and token-name patterns each tried every start in the run and scanned to its end."""
        import time
        for text in ("Na-" * 20000, "a." * 30000, "password" * 7500, "x" * 60000 + "@"):
            t0 = time.time()
            transcript.scrub(text)
            self.assertLess(time.time() - t0, 2, text[:12])     # about 0.1 s each; 5 to 17 s before

    def test_secrets_are_masked_before_anything_is_cut(self):
        """A private key cut in half (pasted text keeps 400 characters, a session line 120) no longer matched the
        pattern, which needs its END line, so its first lines reached the digest and the page."""
        pem = "PRIVATE " + "KEY-----"         # built at run time, so secret scanners see no key header in the file
        key = "-----BEGIN " + pem + "\n" + "\n".join(["MIIEvQIBADAN" + "Bg" * 26] * 12) + "\n-----END " + pem
        path, ids = write_transcript([("<pasted_content>" + key + "</pasted_content> is this right?", ["Do not paste keys."])])
        try:
            meta, entries = transcript.read_session(path)
            self.assertNotIn("BEGIN", transcript.digest(path))
            self.assertNotIn("BEGIN", transcript.session_line(meta, entries))
            self.assertIn("[secret]", transcript.session_line(meta, entries))
        finally:
            os.unlink(path)
        summary = {"k": "C", "at": "2026-09-14T09:00:00.000Z", "msg": ids[0], "text": "1. Primary Request:\n" + "x" * 7900 + "\n" + key}
        self.assertNotIn("BEGIN", transcript._block(summary))       # a compaction summary cut at 8,000 characters
        # a value at the very end of a paste must not swallow the closing tag and, with it, what the user typed after it
        prompt = ("<pasted_content>" + "line of config\n" * 60 + "API_KEY=" + "abcd1234" * 2 + "</pasted_content>\nwhy does it fail?\n"
                  "<pasted_content>" + "log line\n" * 10 + "</pasted_content>")
        block = transcript._block({"k": "P", "at": "2026-09-14T09:00:00.000Z", "msg": ids[0], "text": prompt})
        self.assertIn("why does it fail?", block)
        self.assertEqual(block.count("[/pasted]"), 2)

    def test_a_session_line_skips_pasted_output(self):
        """A first prompt that is another session's output pasted in (it starts with Claude Code's reply marker) said
        nothing about this session, and filled the project page's card with someone else's words."""
        path, _ = write_transcript([("\u23fa Done: the docs and the code agree again, nine fixes today.", ["Noted."]),
                                    ("Now add photo upload to recipes", ["On it."])])
        try:
            meta, entries = transcript.read_session(path)
            self.assertEqual(transcript.session_line(meta, entries), "Now add photo upload to recipes")
        finally:
            os.unlink(path)

    def test_sessions_run_with_claude_p_are_not_interactive(self):
        """claude -p and the Agent SDK record an sdk-... entrypoint on each prompt; such a session (a script, a test) is
        left off the page. A session without the field, or with any prompt typed in a terminal, counts as interactive."""
        for points, want in ((["sdk-cli"], False), (["sdk-ts", "sdk-py"], False), (["sdk-cli", "cli"], True), ([None], True)):
            path, _ = write_transcript([("Prompt number %d here" % i, ["ok"]) for i in range(len(points))])
            try:
                with open(path, encoding="utf-8") as f:
                    recs = [json.loads(line) for line in f]
                left = list(points)
                for r in recs:
                    if r["type"] == "user" and left:
                        point = left.pop(0)
                        if point:
                            r["entrypoint"] = point
                with open(path, "w", encoding="utf-8") as f:
                    f.write("".join(json.dumps(r) + "\n" for r in recs))
                self.assertEqual(transcript.read_session(path)[0]["interactive"], want, points)
            finally:
                os.unlink(path)

    def test_the_excerpt_a_summary_is_written_from(self):
        """What a run reads of another session to summarize it: the title, the first two and last two prompts that are
        neither a nudge nor pasted output, the start of the last reply and the last recap without Claude Code's settings
        hint, scrubbed like a digest and about 1.5 KB at most."""
        key = "sk-" + "ant-" + "api03-" + "abcdefghij" * 3
        path, _ = write_transcript([("\u23fa Pasted: another session's summary of other work.", ["Noted."]),
                                    ("Add photo upload to recipes, the key is " + key, ["Done."]), ("继续", ["ok"]),
                                    ("Second real prompt here", ["ok"]), ("Middle prompt left out", ["ok"]),
                                    ("Fourth real prompt here", ["ok"]), ("Last real prompt: ship it", ["Shipped. " + "y" * 1000])])
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "system", "subtype": "away_summary", "uuid": "ffffffff-0000-4000-8000-000000000000",
                                    "sessionId": "11111111-2222-4333-8444-555555555555", "timestamp": "2026-09-14T10:00:00.000Z",
                                    "content": "You shipped photo upload. (disable recaps in /config)"}) + "\n")
            meta, entries = transcript.read_session(path)
            text = transcript.overview(meta, entries)
        finally:
            os.unlink(path)
        self.assertNotIn("Pasted: another session", text)
        self.assertIn("Add photo upload to recipes, the key is [secret]", text)
        self.assertNotIn("Middle prompt left out", text)
        for kept in ("Second real prompt here", "Fourth real prompt here", "Last real prompt: ship it"):
            self.assertIn(kept, text)
        self.assertIn("last recap 2026-09-14: You shipped photo upload.", text)
        self.assertNotIn("disable recaps", text)
        self.assertIn("\u2026", text)                       # the long last reply is cut
        self.assertLess(len(text), 1700)

    def test_compaction_keeps_pending_tasks(self):
        long = "x " * 3000
        text = ("This session is being continued from a previous conversation that ran out of context.\n\nSummary:\n"
                "1. Primary Request and Intent:\n   build it\n\n2. Key Technical Concepts:\n   " + long + "\n\n"
                "3. Files and Code Sections:\n   " + long + "\n\n7. Pending Tasks:\n   - decide the palette\n   - install the tool\n\n"
                "8. Current Work:\n   drawing\n\n9. Optional Next Step:\n   " + long + "\n")
        out = transcript._trim_compact(text, 2000)
        self.assertIn("- decide the palette", out)
        self.assertIn("- install the tool", out)
        self.assertIn("8. Current Work", out)
        self.assertNotIn("Files and Code Sections", out)
        self.assertIn("2. Key Technical Concepts", out)       # shortened, not dropped
        self.assertLessEqual(len(out), 2000 + 200)

    def test_long_texts_are_kept_whole(self):
        path, _ = write_transcript([("Plan the release " + "and more " * 300, ["Checking.", "Done. " + "detail " * 900 + "Still open: ask Maya about the feed."])])
        try:
            text, info = transcript.digest_pass(path)
        finally:
            os.unlink(path)
        self.assertIn("Still open: ask Maya about the feed.", text)          # the end of a 6,000-character reply
        self.assertIn(("and more " * 300).strip(), text)
        self.assertIn("\nChecking.\n", text)                                 # replies before the last one of a turn too
        self.assertIn("texts shortened: none; everything else is complete", text)
        self.assertNotIn("[cut", text)
        self.assertEqual((info["entries"], info["remaining"], info["passes"]), (3, 0, 1))

    def test_passes_break_between_turns(self):
        turns = [("prompt %d about the release" % i, ["reply %d " % i + "word " * 200, "end of turn %d" % i]) for i in range(12)]
        path, ids = write_transcript(turns)
        try:
            seen, after, passes = [], None, 0
            while True:
                text, info = transcript.digest_pass(path, after=after, max_chars=8000)
                entries = ledger.parse_digest(text)[1]
                if not entries:
                    break
                passes += 1
                first = list(entries.values())[0]
                self.assertEqual(first["kind"], "prompt")                      # each pass starts with a turn
                self.assertLessEqual(len(text), 8000)
                self.assertIn("come in a later pass" if info["remaining"] else "every new entry is in this digest", text)
                seen += list(entries)
                after = list(entries)[-1]
        finally:
            os.unlink(path)
        self.assertGreater(passes, 1)
        self.assertEqual(seen, ids)                                            # all of it, in order, once

    def test_an_entry_longer_than_a_pass_is_cut_and_said_so(self):
        path, ids = write_transcript([("go", ["x " * 6000])])
        try:
            first, info = transcript.digest_pass(path, max_chars=5000)
            second, _ = transcript.digest_pass(path, after=ids[0], max_chars=5000)
        finally:
            os.unlink(path)
        self.assertEqual((info["entries"], info["remaining"]), (1, 1))      # the reply does not fit beside its prompt
        self.assertNotIn("[cut", first)
        self.assertIn("more characters not shown]", second)
        self.assertIn("1 entry longer than a whole digest cut", second)
        self.assertLessEqual(len(second), 5000)

    def test_treesight_traces_are_left_out(self):
        path, ids = write_transcript([("Fix the parser", ["Fixed."])])
        own = [{"type": "user", "uuid": "a0000001-0000-4000-8000-000000000000", "origin": {"kind": "human"},
                "message": {"content": "/treesight:treesight"}},
               {"type": "user", "uuid": "a0000002-0000-4000-8000-000000000000", "origin": {"kind": "task-notification"},
                "message": {"content": '<task-notification><summary>Agent "/treesight:treesight" finished</summary></task-notification>'}},
               {"type": "assistant", "uuid": "a0000003-0000-4000-8000-000000000000", "message": {"content": [{"type": "text", "text": "I checked what treesight flagged."}]}},
               {"type": "user", "uuid": "a0000004-0000-4000-8000-000000000000", "origin": {"kind": "human"}, "message": {"content": "Now add tests"}},
               {"type": "assistant", "uuid": "a0000005-0000-4000-8000-000000000000", "message": {"content": [{"type": "text", "text": "Added."}]}}]
        with open(path, "a", encoding="utf-8") as f:
            for r in own:
                f.write(json.dumps(dict(r, sessionId="11111111-2222-4333-8444-555555555555", timestamp="2026-09-14T10:00:00.000Z")) + "\n")
        try:
            meta, entries = transcript.read_session(path)
            after_command = transcript.entries_after(path, entries, "a0000001-0000-4000-8000-000000000000")
            with self.assertRaises(ValueError):
                transcript.entries_after(path, entries, "ffffffff-0000-4000-8000-000000000000")
        finally:
            os.unlink(path)
        self.assertEqual(meta["prompts"]["total"], 2)
        self.assertEqual([e["text"] for e in entries], ["Fix the parser", "Fixed.", "Now add tests", "Added."])
        self.assertEqual([e["text"] for e in after_command], ["Now add tests", "Added."])   # a ledger that stopped at the command goes on

    def test_a_quoted_entry_header_is_not_an_entry(self):
        fake = "[reply 2026-09-14T09:00:00.000Z 99999999-0000-4000-8000-000000000000]"
        path, ids = write_transcript([("Show me a digest line", ["Here is one:\n" + fake + "\nDone.\nStill open: ask Maya."])])
        try:
            text = transcript.digest(path)
        finally:
            os.unlink(path)
        entries = ledger.parse_digest(text)[1]
        self.assertEqual(list(entries), ids)
        self.assertIn("Still open: ask Maya.", entries[ids[-1]]["text"])
        self.assertTrue(ledger.quote_found(fake + "\nDone.", entries[ids[-1]]["text"]))   # quotes still match

    def test_work_after_a_treesight_turn_counts_again(self):
        path, _ = write_transcript([("Fix the parser", ["Fixed."])])
        recs = [{"type": "user", "uuid": "b0000001-0000-4000-8000-000000000000", "origin": {"kind": "human"}, "message": {"content": "/treesight"}},
                {"type": "assistant", "uuid": "b0000002-0000-4000-8000-000000000000", "message": {"content": [{"type": "text", "text": "treesight is drawing."}]}},
                {"type": "user", "uuid": "b0000003-0000-4000-8000-000000000000",
                 "message": {"content": "<command-message>review</command-message>\n<command-name>/review</command-name>"}},
                {"type": "assistant", "uuid": "b0000004-0000-4000-8000-000000000000", "message": {"content": [{"type": "text", "text": "Review: fix the race before release."}]}},
                {"type": "user", "uuid": "b0000005-0000-4000-8000-000000000000", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
                {"type": "assistant", "uuid": "b0000006-0000-4000-8000-000000000000", "message": {"content": [{"type": "text", "text": "And the docs."}]}}]
        with open(path, "a", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(dict(r, sessionId="11111111-2222-4333-8444-555555555555", timestamp="2026-09-14T10:00:00.000Z")) + "\n")
        try:
            _, entries = transcript.read_session(path)
        finally:
            os.unlink(path)
        self.assertEqual([e["text"] for e in entries], ["Fix the parser", "Fixed.", "Review: fix the race before release.", "And the docs."])

    def test_digest_cuts(self):
        full = transcript.digest(FIXTURE)
        self.assertNotIn("Files and Code Sections", full)
        self.assertNotIn("All user messages", full)
        self.assertIn("Optional Next Step", full)
        _, entries = ledger.parse_digest(full)
        self.assertEqual(len(entries), 34)   # 15 prompts, 16 replies (one turn has two), 2 recaps, 1 compaction
        first = list(entries)
        after = transcript.digest(FIXTURE, after=first[9])
        self.assertEqual(len(ledger.parse_digest(after)[1]), 24)
        until = transcript.digest(FIXTURE, until="2026-09-14T12:00:00Z")
        self.assertTrue(all(e["at"] <= "2026-09-14T12:00:00Z" for e in ledger.parse_digest(until)[1].values()))


class Check(unittest.TestCase):
    digest = transcript.digest(FIXTURE)

    def test_fixture_passes(self):
        self.assertEqual(ledger.check(EXTRACT, self.digest), [])

    def test_quote_must_be_verbatim(self):
        e = copy.deepcopy(EXTRACT)
        e["nodes"][0]["evidence"][0]["quote"] = "Something the session never said."
        self.assertTrue(any("quote not found" in p for p in ledger.check(e, self.digest)))

    def test_whitespace_and_ellipsis_are_tolerated(self):
        e = copy.deepcopy(EXTRACT)
        q = e["nodes"][0]["evidence"][0]["quote"]
        e["nodes"][0]["evidence"][0]["quote"] = "... " + q.replace(" ", "\n  ", 1) + " ..."
        self.assertEqual(ledger.check(e, self.digest), [])

    def test_time_and_ids(self):
        e = copy.deepcopy(EXTRACT); e["nodes"][0]["at"] = "2026-09-14T00:00:00Z"
        self.assertTrue(ledger.check(e, self.digest))
        e = copy.deepcopy(EXTRACT); e["open"][0]["blocked_by"] = "o99"
        self.assertTrue(ledger.check(e, self.digest))
        e = copy.deepcopy(EXTRACT); e["close"] = [{"id": "953c0ab1-o1", "status": "done", "sure": True, "quote": "Good.", "msg": EXTRACT["through"], "at": "2026-09-15T09:48:01.000Z"}]
        self.assertTrue(any("not an open item" in p for p in ledger.check(e, self.digest)))
        known = {"nodes": [], "open": [{"id": "953c0ab1-o1", "kind": "todo", "label": "x", "line": "y"}]}
        e["close"][0]["quote"] = "You're getting tidepool 0.3.0 ready."
        self.assertEqual(ledger.check(e, self.digest, known), [])


if __name__ == "__main__":
    unittest.main()

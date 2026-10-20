"""scripts/treesight.py, the commands the skill runs, on the made-up project. Run: python3 -m unittest -v"""
import contextlib
import glob
import io
import json
import multiprocessing
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import ledger  # noqa: E402
import treesight  # noqa: E402

S1, S2 = "953c0ab1-134d-56c9-9224-a2eb69918a2a", "0a182a7b-3fd8-56b9-a6e6-9fc77576e221"
PROJECT = "-home-dev-tidepool"


def run(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = treesight.main(list(args))
    text = out.getvalue().strip()
    return code, (json.loads(text) if text.startswith(("{", "[")) else text)


def page_data(path):
    with open(path, encoding="utf-8") as f:
        html = f.read()
    return html, json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1))


def empty_extract(digest_path):
    """A valid extraction of a digest that adds nothing: enough to move the ledger on in pass tests."""
    with open(digest_path, encoding="utf-8") as f:
        sid, entries = ledger.parse_digest(f.read())
    return {"schema": "treesight/extract@1", "session": sid, "through": list(entries)[-1], "nodes": [], "open": [], "close": []}


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="treesight-cli-")
        os.environ["TREESIGHT_HOME"] = os.path.join(self.tmp, "home")
        os.environ["TREESIGHT_WORK"] = os.path.join(self.tmp, "work")
        os.environ["TREESIGHT_PROJECTS"] = os.path.join(ROOT, "fixtures", "projects")
        self.cache = os.path.join(self.tmp, "cache")
        self.common = ["--current", S1, "--cache", self.cache]

    def tearDown(self):
        for k in ("TREESIGHT_HOME", "TREESIGHT_PROJECTS", "TREESIGHT_WORK"):
            os.environ.pop(k, None)
        shutil.rmtree(self.tmp)

    def first_run(self, *common):
        common = common or self.common
        code, out = run("prepare", *common)
        self.assertEqual(code, 0, out)
        shutil.copy(os.path.join(ROOT, "fixtures", "extract", "tidepool-1.json"), out["extract"])
        code, res = run("apply", *common)
        self.assertEqual((code, res["ok"]), (0, True), res)
        code, _ = run("build", "--done", "--session", S1, *common)
        self.assertEqual(code, 0)
        return out, res

    def test_find_session(self):
        f = treesight.find_session
        self.assertIn(S1, f("", S1))
        self.assertIn(S2, f("0a182a7b", S1))
        self.assertIn(S2, f("release 0.3", S1))
        self.assertIn(S2, f(f("0a182a7b", S1), None))
        with self.assertRaises(treesight.Problem):
            f("no such title", S1)
        with self.assertRaises(treesight.Problem):
            f("", None)

    def test_prepare_apply_then_nothing_new(self):
        out, res = self.first_run()
        self.assertEqual(out["new_entries"], 34)
        self.assertEqual((out["parts"], out["entries_after_this_pass"]), (1, 0))
        self.assertEqual((res["entries_left"], res["go_on"]), (0, False))
        self.assertTrue(out["extract"].startswith(os.environ["TREESIGHT_WORK"]))
        self.assertFalse(glob.glob(os.path.join(os.environ["TREESIGHT_WORK"], PROJECT, "*")))   # removed once in the ledger
        code, again = run("prepare", *self.common)
        self.assertTrue(again["nothing_new"])
        self.assertNotIn("extract", again)

    def test_files_are_private(self):
        self.first_run()
        d = ledger.project_dir(PROJECT)
        self.assertEqual(oct(os.stat(d).st_mode & 0o777), "0o700")
        self.assertEqual(oct(os.stat(os.path.join(d, "ledger.jsonl")).st_mode & 0o777), "0o600")
        page = glob.glob(os.path.join(self.cache, "pages", "*.html"))[0]
        self.assertEqual(oct(os.stat(page).st_mode & 0o777), "0o600")
        code, out = run("prepare", "--session", S2, *self.common)
        self.assertEqual(oct(os.stat(os.path.dirname(out["extract"])).st_mode & 0o777), "0o700")
        digest = out["extract"].replace(".extract.json", ".digest.txt")
        self.assertEqual(oct(os.stat(digest).st_mode & 0o777), "0o600")

    def test_apply_without_extract_fails_cleanly(self):
        run("prepare", *self.common)
        code, res = run("apply", *self.common)
        self.assertEqual(code, 1)
        self.assertIn("no extraction", res["error"])

    def test_a_session_being_drawn_is_not_drawn_twice(self):
        code, out = run("prepare", *self.common)
        code, again = run("prepare", *self.common)
        self.assertTrue(again.get("busy"), again)
        self.assertNotIn("new_entries", again)
        self.assertTrue(os.path.exists(out["extract"].replace(".extract.json", ".digest.txt")))   # the first run's digest is kept
        before = treesight.read_job(self.cache, PROJECT, S1)["estimate_s"]
        code, cont = run("prepare", "--continue", *self.common)    # the run itself goes on
        self.assertEqual((code, cont["pass_number"]), (0, 2))
        self.assertEqual(treesight.read_job(self.cache, PROJECT, S1)["estimate_s"], before)   # the page times the whole run
        run("build", "--done", "--session", S1, *self.common)
        code, fresh = run("prepare", *self.common)
        self.assertEqual((fresh.get("busy"), fresh["pass_number"]), (None, 1))

    def test_a_stopped_run_does_not_block_the_next(self):
        code, out = run("prepare", *self.common)
        mark = glob.glob(os.path.join(self.cache, "jobs", PROJECT, "*.json"))[0]
        with open(mark, encoding="utf-8") as f:
            job = json.load(f)
        job.update(touched=time.time() - 25 * 60, started=time.time() - 30 * 60, estimate_s=120)   # well past its estimate, quiet
        with open(mark, "w", encoding="utf-8") as f:
            json.dump(job, f)
        self.assertEqual(treesight.live_jobs(self.cache, PROJECT), [])
        code, again = run("prepare", *self.common)
        self.assertNotIn("busy", again)
        self.assertEqual(again["pass_number"], 1)
        run("build", "--session", S1, *self.common)                     # a build without --done keeps the mark
        self.assertEqual(len(treesight.live_jobs(self.cache, PROJECT)), 1)

    def test_reopen_finds_items_to_confirm_by_their_words(self):
        self.first_run()
        code, out = run("prepare", "--session", S2, *self.common)
        shutil.copy(os.path.join(ROOT, "fixtures", "extract", "tidepool-2.json"), out["extract"])
        code, res = run("apply", "--session", S2, *self.common)
        self.assertTrue(res["ok"], res)
        unsure = [o for o in ledger.load(PROJECT)["open"] if o["state"] != "open"]
        self.assertTrue(unsure)
        code, e = run("edit", "reopen", unsure[0]["id"], *self.common)
        self.assertEqual((code, e["ev"]), (0, "reopen"))

    def test_show_guide_and_digest_parts(self):
        code, guide = run("show", "guide")
        self.assertEqual(code, 0)
        self.assertIn("# How to extract a session", guide)
        self.assertIn("schema/extract.schema.json", guide)
        self.assertLess(len(guide), 25000)          # one Bash result shows about 30,000 characters inline
        code, out = run("prepare", *self.common)
        code, part = run("show", "digest", "--part", "1", *self.common)
        self.assertTrue(part.startswith("# treesight digest"))
        self.assertTrue(part.endswith("[end of part 1 of 1; that was the last part]"))
        code, err = run("show", "digest", "--part", "2", *self.common)
        self.assertEqual(code, 1)
        self.assertIn("no part 2", err["error"])

    def test_split_parts(self):
        blocks = ["[reply 2026-09-14T09:%02d:00.000Z %08d-0000-4000-8000-000000000000]\n%s" % (i, i, "word " * 300) for i in range(10)]
        text = "# treesight digest\nsession: x\n\n---\n\n" + "\n\n".join(blocks) + "\n"
        parts = treesight.split_parts(text, 4000)
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(len(p) <= 4000 for p in parts))
        self.assertTrue(all(p.startswith(("# treesight", "[reply ")) for p in parts))     # broken before an entry
        long = "[reply 2026-09-14T09:00:00.000Z 00000001-0000-4000-8000-000000000000]\n" + ("line of text\n" * 1000)
        parts = treesight.split_parts(long, 4000)
        self.assertEqual("".join(parts), long)
        self.assertTrue(all(len(p) <= 4000 for p in parts))

    def test_long_sessions_are_read_in_passes(self):
        seen, go_on = [], False
        while True:
            code, out = run("prepare", "--max-chars", "3000", *(["--continue"] if go_on else []), *self.common)
            if out.get("nothing_new"):
                break
            dig = out["extract"].replace(".extract.json", ".digest.txt")
            with open(dig, encoding="utf-8") as f:
                text = f.read()
            seen += list(ledger.parse_digest(text)[1])
            self.assertIn("come in a later pass" if out["entries_after_this_pass"] else "every new entry is in this digest", text)
            with open(out["extract"], "w", encoding="utf-8") as f:
                json.dump(empty_extract(dig), f)
            code, res = run("apply", *self.common)
            self.assertTrue(res["ok"], res)
            go_on = res["go_on"]
            if not go_on:
                if res["entries_left"]:                    # stopped after the most passes one run may do
                    self.assertEqual(out["pass_number"], treesight.MAX_PASSES)
                run("build", "--done", "--session", S1, *self.common)
        self.assertEqual(len(seen), 34)            # every entry read once, none twice
        self.assertEqual(len(set(seen)), 34)
        self.assertGreater(ledger.load(PROJECT)["sessions"][S1]["runs"], 2)

    def test_edit_by_label_words_and_build(self):
        self.first_run()
        code, e = run("edit", "close", "windows", "support", *self.common)
        self.assertEqual((code, e["ev"]), (0, "close"))
        code, e = run("edit", "reopen", "windows", "support", *self.common)   # a closed item, found by its words
        self.assertEqual((code, e["ev"]), (0, "reopen"))
        code, e = run("edit", "set", "maya", "--field", "rank=1", *self.common)
        self.assertEqual(e["fields"], {"rank": 1})
        code, e = run("edit", "close", "PyPI", *self.common)   # matches the token item and the release item
        self.assertEqual(code, 1)
        self.assertIn("more than one", e["error"])
        code, rows = run("list", *self.common)
        self.assertEqual([r["tree"] for r in rows if r["id"] == S1[:8]], [True])
        code, b = run("build", *self.common)
        self.assertEqual(code, 0)

    def test_edits_are_checked_before_they_are_recorded(self):
        self.first_run()
        edits = os.path.join(ledger.project_dir(PROJECT), "edits.jsonl")
        node = ledger.load(PROJECT)["sessions"][S1]["nodes"][0]["id"]
        for args in (["set", "maya", "--field", "kind=done"], ["set", "maya", "--field", "label=one two three four five six seven eight nine"],
                     ["set", "maya", "--field", "due=next week"], ["set", "maya", "--field", "blocked_by=953c0ab1-o99"],
                     ["set", "windows", "--field", "kind=todo", "--field", "who=Maya"], ["close", node], ["reopen", "maya"],
                     ["set", "maya", "--field", "msg=x"]):
            code, e = run("edit", *args, *self.common)
            self.assertEqual(code, 1, (args, e))
        self.assertFalse(os.path.exists(edits))           # none of them was written
        code, b = run("build", *self.common)
        self.assertEqual(code, 0)

    def test_page_opens_on_its_session_and_lists_every_run_in_progress(self):
        self.first_run()
        run("prepare", "--session", S1, *self.common)     # nothing new for S1
        code, a = run("prepare", "--session", S2, *self.common)
        self.assertFalse(a.get("nothing_new"))
        code, _ = run("build", "--session", S2, *self.common)
        page = glob.glob(os.path.join(self.cache, "pages", "*.html"))[0]
        html, d = page_data(page)
        self.assertEqual([p["session"] for p in d["pending"]], [S2])
        self.assertIn('http-equiv="refresh"', html)
        self.assertEqual(d["focus"], S2)
        code, _ = run("build", "--done", "--session", S2, *self.common)
        html, d = page_data(page)
        self.assertNotIn("pending", d)
        self.assertNotIn('http-equiv="refresh"', html)

    @unittest.skipUnless(ledger.fcntl, "no file locks on this system")
    def test_a_build_that_read_an_older_state_cannot_write_its_page_last(self):
        self.first_run()
        code, out = run("prepare", "--session", S2, *self.common)      # S2 is being drawn
        shutil.copy(os.path.join(ROOT, "fixtures", "extract", "tidepool-2.json"), out["extract"])
        ctx = multiprocessing.get_context("fork")
        ready, release = ctx.Event(), ctx.Event()

        def first_builder():     # a build that has read the ledger and the marks and is about to write its page
            write = ledger.write_private

            def paused(path, text):
                if path.endswith(".html"):
                    ready.set()
                    release.wait(10)
                return write(path, text)
            ledger.write_private = paused
            run("build", "--session", S1, *self.common)
        p = ctx.Process(target=first_builder)
        p.start()
        self.assertTrue(ready.wait(10))
        results = []
        finish = threading.Thread(target=lambda: results.extend([run("apply", "--session", S2, *self.common),
                                                                 run("build", "--done", "--session", S2, *self.common)]))
        finish.start()
        finish.join(0.5)
        self.assertTrue(finish.is_alive())          # S2's run waits until the older page is written
        release.set()
        p.join(10)
        finish.join(10)
        self.assertEqual(results[0][1]["ok"], True, results)
        html, d = page_data(glob.glob(os.path.join(self.cache, "pages", "*.html"))[0])
        self.assertEqual(sum(s["generated"] for s in d["sessions"]), 2)
        self.assertNotIn("pending", d)
        self.assertNotIn('http-equiv="refresh"', html)

    @unittest.skipUnless(ledger.fcntl, "no file locks on this system")
    def test_two_builds_at_once_cannot_leave_a_finished_run_shown_as_in_progress(self):
        self.first_run()
        code, out = run("prepare", "--session", S2, *self.common)      # S2 is being drawn
        shutil.copy(os.path.join(ROOT, "fixtures", "extract", "tidepool-2.json"), out["extract"])
        run("apply", "--session", S2, *self.common)
        ctx = multiprocessing.get_context("fork")
        ready, release = ctx.Event(), ctx.Event()

        def progress_builder():     # a build that has seen S2's mark and is about to write a page saying S2 is drawn
            write = ledger.write_private

            def paused(path, text):
                if path.endswith(".html"):
                    ready.set()
                    release.wait(10)
                return write(path, text)
            ledger.write_private = paused
            run("build", "--session", S1, *self.common)
        p = ctx.Process(target=progress_builder)
        p.start()
        self.assertTrue(ready.wait(10))
        done = threading.Thread(target=lambda: run("build", "--done", "--session", S2, *self.common))
        done.start()
        done.join(0.5)
        self.assertTrue(done.is_alive())            # S2's last build waits, then writes after the older one
        release.set()
        p.join(10)
        done.join(10)
        html, d = page_data(glob.glob(os.path.join(self.cache, "pages", "*.html"))[0])
        self.assertNotIn("pending", d)
        self.assertNotIn('http-equiv="refresh"', html)
        self.assertEqual(d["focus"], S2)

    def test_the_project_starts_with_its_earliest_session_even_when_that_one_was_active_last(self):
        projects = os.path.join(self.tmp, "projects")
        shutil.copytree(os.path.join(ROOT, "fixtures", "projects"), projects)
        os.environ["TREESIGHT_PROJECTS"] = projects
        with open(glob.glob(os.path.join(projects, PROJECT, S1 + ".jsonl"))[0], "a", encoding="utf-8") as f:     # S1 resumed weeks later
            f.write(json.dumps({"type": "user", "sessionId": S1, "timestamp": "2026-10-19T05:16:34.000Z", "uuid": "a0000000-0000-4000-8000-000000000000",
                                "origin": {"kind": "human"}, "message": {"role": "user", "content": "Back to tidepool: what is left?"}}) + "\n")
        run("build", *self.common)
        html, d = page_data(glob.glob(os.path.join(self.cache, "pages", "*.html"))[0])
        s = {x["id"]: x for x in d["sessions"]}
        self.assertEqual(max(s.values(), key=lambda x: x["last_at"])["id"], S1)
        self.assertEqual(d["project"]["first_at"], s[S1]["first_at"])
        self.assertLess(d["project"]["first_at"], s[S2]["first_at"])

    def test_what_the_user_writes_during_a_run_waits_for_the_next_run(self):
        projects = os.path.join(self.tmp, "projects")
        shutil.copytree(os.path.join(ROOT, "fixtures", "projects"), projects)
        os.environ["TREESIGHT_PROJECTS"] = projects
        code, out = run("prepare", *self.common)                       # every entry fits in this pass
        self.assertEqual(out["entries_after_this_pass"], 0)
        shutil.copy(os.path.join(ROOT, "fixtures", "extract", "tidepool-1.json"), out["extract"])
        with open(os.path.join(projects, PROJECT, S1 + ".jsonl"), "a", encoding="utf-8") as f:      # the user keeps working meanwhile
            for i, (kind, content) in enumerate((("user", "Now add a --days flag to export"),
                                                 ("assistant", [{"type": "text", "text": "Added --days; it defaults to 7."}]))):
                rec = {"type": kind, "sessionId": S1, "timestamp": "2026-10-19T10:00:0%dZ" % i, "uuid": "c000000%d-0000-4000-8000-000000000000" % i,
                       "message": {"role": kind, "content": content}}
                if kind == "user":
                    rec["origin"] = {"kind": "human"}
                f.write(json.dumps(rec) + "\n")
        code, res = run("apply", *self.common)
        self.assertTrue(res["ok"], res)
        self.assertEqual((res["entries_left"], res["go_on"]), (2, False))
        run("build", "--done", "--session", S1, *self.common)
        code, again = run("prepare", *self.common)                     # the next run picks them up
        self.assertEqual(again["new_entries"], 2)

    def test_a_session_with_no_prompt_yet_says_so(self):
        projects = os.path.join(self.tmp, "projects")
        shutil.copytree(os.path.join(ROOT, "fixtures", "projects"), projects)
        os.environ["TREESIGHT_PROJECTS"] = projects
        fresh = "b1000000-0000-4000-8000-000000000000"
        with open(os.path.join(projects, PROJECT, fresh + ".jsonl"), "w", encoding="utf-8") as f:     # started only to run /treesight
            for r in ({"type": "user", "isMeta": True, "uuid": "b1000000-0000-4000-8000-000000000001", "message": {"role": "user", "content": "<local-command-caveat>Caveat</local-command-caveat>"}},
                      {"type": "user", "uuid": "b1000000-0000-4000-8000-000000000002", "origin": {"kind": "human"}, "message": {"role": "user", "content": "/treesight:treesight"}}):
                f.write(json.dumps(dict({"sessionId": fresh, "timestamp": "2026-10-19T10:39:57.000Z", "cwd": "/home/dev/tidepool"}, **r)) + "\n")
        code, out = run("prepare", "--current", fresh, "--cache", self.cache)
        self.assertEqual((code, out["nothing_new"], out.get("empty")), (0, True, True), out)
        code, out = run("prepare", *self.common)                     # a session with prompts is never called empty
        self.assertNotIn("empty", out)

    def test_treesight_runs_in_the_current_session_are_not_new_content(self):
        projects = os.path.join(self.tmp, "projects")
        shutil.copytree(os.path.join(ROOT, "fixtures", "projects"), projects)
        os.environ["TREESIGHT_PROJECTS"] = projects
        path = glob.glob(os.path.join(projects, PROJECT, S1 + ".jsonl"))[0]
        self.first_run()

        def add(*recs):
            with open(path, "a", encoding="utf-8") as f:
                for r in recs:
                    f.write(json.dumps(dict({"sessionId": S1, "timestamp": "2026-09-16T10:00:00.000Z"}, **r)) + "\n")
        n = iter(range(100))
        uid = lambda: "%08x-0000-4000-8000-000000000000" % (0xa0000000 + next(n))
        # the shapes Claude Code 2.1.299 writes for a background /treesight and the main conversation's reaction
        add({"type": "user", "isMeta": True, "uuid": uid(), "message": {"role": "user", "content": "<local-command-caveat>Caveat</local-command-caveat>"}},
            {"type": "user", "uuid": uid(), "origin": {"kind": "human"}, "message": {"role": "user", "content": "/treesight:treesight"}},
            {"type": "system", "subtype": "local_command", "uuid": uid(), "content": "<local-command-stdout>Running in the background</local-command-stdout>"},
            {"type": "user", "uuid": uid(), "origin": {"kind": "task-notification"},
             "message": {"role": "user", "content": '<task-notification>\n<summary>Agent "/treesight:treesight" finished</summary>\n</task-notification>'}},
            {"type": "assistant", "uuid": uid(), "message": {"role": "assistant", "content": [{"type": "text", "text": "treesight drew the tree; I checked the replies it flagged."}]}},
            {"type": "user", "uuid": uid(), "message": {"role": "user", "content": "[Request interrupted by user for tool use]"}})
        code, out = run("prepare", *self.common)
        self.assertTrue(out["nothing_new"], out)
        add({"type": "user", "uuid": uid(), "origin": {"kind": "human"}, "message": {"role": "user", "content": "Draft the release blog post"}},
            {"type": "assistant", "uuid": uid(), "message": {"role": "assistant", "content": [{"type": "text", "text": "Here is a draft."}]}})
        code, out = run("prepare", *self.common)
        self.assertEqual(out["new_entries"], 2)


if __name__ == "__main__":
    unittest.main()

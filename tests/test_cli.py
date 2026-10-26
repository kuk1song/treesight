"""scripts/treesight.py, the commands the skill runs, on the made-up project. Run: python3 -m unittest discover -s tests"""
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
from unittest import mock

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import build  # noqa: E402
import ledger  # noqa: E402
import treesight  # noqa: E402

S1, S2 = "953c0ab1-134d-56c9-9224-a2eb69918a2a", "0a182a7b-3fd8-56b9-a6e6-9fc77576e221"
PROJECT = "-home-dev-tidepool"


def run(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = treesight.main(list(args))
    text = out.getvalue().strip()
    try:
        return code, json.loads(text)
    except ValueError:      # what `show` prints for the model to read
        return code, text


def page_data(path):
    with open(path, encoding="utf-8") as f:
        html = f.read()
    return html, json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1))


def stamp(page):
    """What the stamp next to a page says: the build it names, the session it is about, and whether a run is going on."""
    with open(build.stamp_path(page), encoding="utf-8") as f:
        return json.loads(re.search(r"__treesight\((.*)\);", f.read()).group(1))


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

    def test_a_finished_run_leaves_no_work_files(self):
        code, out = run("prepare", *self.common)
        with open(out["extract"], "w", encoding="utf-8") as f:
            f.write("{not json")                     # the run fails: apply keeps the files so the model could retry
        code, res = run("apply", *self.common)
        self.assertNotEqual(code, 0)
        digest = out["extract"].replace(".extract.json", ".digest.txt")
        others = [out["extract"].replace(".extract.json", x) for x in (".others.txt", ".others.json")]
        self.assertTrue(all(os.path.exists(p) for p in [digest, out["extract"]] + others))
        code, _ = run("build", "--done", "--session", S1, *self.common)
        self.assertEqual(code, 0)
        self.assertFalse(any(os.path.exists(p) for p in others))
        self.assertFalse(os.path.exists(digest) or os.path.exists(out["extract"]))

    def test_errors_come_back_as_json(self):
        code, out = run("build", "--current", S1, "--cache", "/dev/null/x")     # a path that cannot be a folder
        self.assertEqual((code, out["ok"]), (1, False), out)
        self.first_run()
        code, out = run("edit", "set", "Ask Maya", "--field", "rank", *self.common)
        self.assertIn("expected FIELD=VALUE", out["error"])
        code, out = run("edit", "set", "Ask Maya", "--field", "rank=first", *self.common)
        self.assertIn("whole number", out["error"])

    def test_an_existing_folder_keeps_its_mode(self):
        d = os.path.join(self.tmp, "shared")
        os.makedirs(d)
        os.chmod(d, 0o755)
        ledger.private_dir(d)
        self.assertEqual(oct(os.stat(d).st_mode & 0o777), "0o755")
        new = ledger.private_dir(os.path.join(self.tmp, "fresh"))
        self.assertEqual(oct(os.stat(new).st_mode & 0o777), "0o700")

    def test_find_session(self):
        f = treesight.find_session
        self.assertIn(S1, f("", S1))
        self.assertIn(S2, f("0a182a7b", S1))
        self.assertIn(S2, f("release 0.3", S1))
        self.assertIn(S2, f(f("0a182a7b", S1), None))
        self.assertIn(S1, f("tidepool NOAA", S1))           # each word anywhere in the title, in any order
        self.assertIn("0c0f810a", f("0c0f810a", S1))         # a whole short id finds a session of another project
        for name in ("no such title", "0c0f"):               # a short number is not taken for another project's session
            with self.assertRaises(treesight.Problem):
                f(name, S1)
        with self.assertRaises(treesight.Problem) as e:
            f("a", S1)                                        # in several titles: they are listed, so the user can pick
        self.assertIn("\u201cAdd ICS export", str(e.exception))
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

    def test_what_a_run_was_unsure_about_stays_in_the_ledger(self):
        """The run's notes are kept in the ledger for checking later, but neither the page nor its data carries them
        (the author found the line under the title noise next to the tree, 2026-10-26)."""
        self.first_run()
        self.assertTrue(ledger.load(PROJECT)["sessions"][S1]["last_run"]["notes"].startswith("o4 (publish 0.3.0)"))
        code, b = run("build", *self.common)
        html, data = page_data(b["page"])
        self.assertNotIn("notes", next(s for s in data["sessions"] if s["id"] == S1)["last_run"])
        self.assertNotIn("o4 (publish 0.3.0)", html)

    def test_a_run_in_two_passes_is_one_run_on_the_page(self):
        """What both passes were unsure about is kept, and apply's counts are the whole run's, as the page's."""
        code, out = run("prepare", "--max-chars", "3000", *self.common)
        self.assertEqual(out["others"], 2)
        for n in (1, 2):
            dig = out["extract"].replace(".extract.json", ".digest.txt")
            with open(out["extract"], "w", encoding="utf-8") as f:
                json.dump(dict(empty_extract(dig), notes="pass %d was unsure" % n), f)
            code, res = run("apply", *self.common)
            self.assertTrue(res["ok"], res)
            if n == 1:
                self.assertTrue(res["go_on"], res)
                code, out = run("prepare", "--continue", "--max-chars", "3000", *self.common)
                self.assertEqual((out["pass_number"], out["others"]), (2, 0))
                with open(out["extract"], "w", encoding="utf-8") as f:
                    json.dump(dict(empty_extract(out["extract"].replace(".extract.json", ".digest.txt")),
                                   others=[{"session": "0a182a7b", "gist": "x"}]), f)
                code, refused = run("apply", *self.common)
                self.assertIn("is not one of the sessions show others listed", " ".join(refused["problems"]))
        run("build", "--done", "--session", S1, *self.common)
        code, b = run("build", *self.common)
        html, data = page_data(b["page"])
        self.assertIn("last_run", next(s for s in data["sessions"] if s["id"] == S1))
        led = ledger.load(PROJECT)["sessions"][S1]
        self.assertEqual((led["last_run"]["notes"], led["runs"]), ("pass 1 was unsure\n\npass 2 was unsure", 2))

    def test_the_report_is_a_line_and_a_half_for_the_user(self):
        """After a run that applied, build --done writes the whole report: the fixed line the hook looks for, then what
        changed (only what is not zero) and the page's link, in the language of the session's prompts."""
        code, out = run("prepare", *self.common)
        shutil.copy(os.path.join(ROOT, "fixtures", "extract", "tidepool-1.json"), out["extract"])
        code, res = run("apply", *self.common)
        code, b = run("build", "--done", "--session", S1, *self.common)
        head, blank, first, page = b["report"].split("\n")[:4]
        self.assertEqual((head, blank), (treesight.REPORT_HEAD, ""))
        self.assertTrue(first.startswith("🌳 treesight: the tree of \u201c%s\u201d is ready: %d new nodes, %d new open items" % (out["title"], res["nodes"], res["open"])), first)
        self.assertEqual(page, "Page updated: " + b["url"])
        self.assertNotIn(" 0 ", b["report"])

    def test_report_wording(self):
        job = lambda **said: {"title": "发布 0.3.0", "said": dict({"nodes": 0, "open": 0, "closed": 0, "to_confirm": 0, "entries_left": 0}, **said)}
        zh = lambda **said: treesight.report(job(**said), "file:///p.html", "zh").split("\n")[2:]
        en = lambda **said: treesight.report(job(**said), "file:///p.html", "en").split("\n")[2:]
        self.assertEqual(zh(nodes=6, open=14), ["🌳 treesight：「发布 0.3.0」的树已生成，新增 6 个节点、14 件待完成。", "页面已更新：file:///p.html"])
        self.assertEqual(zh(open=2, closed=1, to_confirm=2, entries_left=120)[0::2],
                         ["🌳 treesight：「发布 0.3.0」的树已生成，新增 2 件待完成，关掉 1 件。", "有 2 件看起来做完了，等你在页面上确认。"])
        self.assertEqual(zh(entries_left=120)[-1], "这个会话还有 120 条没读，再运行一次会接着读。")
        self.assertEqual(zh()[0], "🌳 treesight：「发布 0.3.0」的树已生成，这次没有新内容。")
        self.assertEqual(en(nodes=1, open=1, closed=2), ["🌳 treesight: the tree of \u201c发布 0.3.0\u201d is ready: 1 new node, 1 new open item, 2 closed.", "Page updated: file:///p.html"])
        self.assertEqual(en(to_confirm=1, entries_left=1)[2:], ["1 looks done; confirm it on the page.", "1 entry of this session is not read yet; run treesight again to go on."])
        self.assertEqual(en(to_confirm=3)[2], "3 look done; confirm them on the page.")
        self.assertEqual(en()[0], "🌳 treesight: the tree of \u201c发布 0.3.0\u201d is ready: nothing new this time.")

    def test_the_report_follows_the_language_of_the_prompts(self):
        P = lambda *texts: [{"k": "P", "text": t} for t in texts] + [{"k": "R", "text": "A long English reply " * 50}]
        self.assertEqual(treesight.report_lang(P("全面仔细遍历检查 README 和 docs/design.md", "继续")), "zh")
        self.assertEqual(treesight.report_lang(P("Please fix the parser", "看一下")), "en")
        self.assertEqual(treesight.report_lang(P("<pasted_content id=\"1\">" + "很长的中文日志" * 50 + "</pasted_content> what is this?")), "en")
        self.assertEqual(treesight.report_lang(P("```\nconst a = 1; let b = 2; foo bar baz\n```\n为什么报错")), "zh")
        self.assertEqual(treesight.report_lang([]), "en")

    def test_a_run_that_did_not_apply_has_no_report(self):
        """The skill then reports the problems itself; a report built from the ledger would describe an earlier run."""
        run("prepare", *self.common)
        code, b = run("build", "--done", "--session", S1, *self.common)
        self.assertNotIn("report", b)

    def test_the_overviews_a_run_is_writing_say_so(self):
        """While a run is drawing, a session whose overview its first pass is writing is marked, so the page says the
        overview is on its way instead of offering one that is not there yet."""
        code, out = run("prepare", *self.common)
        code, b = run("build", "--open", "--session", S1, *self.common)
        html, data = page_data(b["page"])
        writing = {s["id"][:8] for s in data["sessions"] if s.get("summarizing")}
        with open(out["extract"].replace(".extract.json", ".others.json"), encoding="utf-8") as f:
            self.assertEqual(writing, set(json.load(f)))
        self.assertTrue(writing)
        shutil.copy(os.path.join(ROOT, "fixtures", "extract", "tidepool-1.json"), out["extract"])
        run("apply", *self.common)
        code, b = run("build", "--done", "--session", S1, *self.common)
        self.assertFalse([s for s in page_data(b["page"])[1]["sessions"] if s.get("summarizing")])

    def test_the_white_dot_stays_with_the_conversation_the_user_came_from(self):
        """A run started from the page's link runs in a new conversation that holds only the command: it is not listed,
        so the page keeps marking the conversation that last ran treesight and is listed."""
        projects = os.path.join(self.tmp, "projects")
        folder = os.path.join(projects, PROJECT)
        shutil.copytree(os.path.join(ROOT, "fixtures", "projects", PROJECT), folder)
        X = "77777777-0000-4000-8000-000000000000"
        with open(os.path.join(folder, X + ".jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "uuid": "aaaaaaaa-0000-4000-8000-000000000009", "sessionId": X, "cwd": "/home/dev/tidepool",
                                "timestamp": "2026-10-10T09:00:00.000Z", "entrypoint": "cli", "origin": {"kind": "human"},
                                "message": {"role": "user", "content": "/treesight:treesight 0a182a7b --no-open"}}) + "\n")
        os.environ["TREESIGHT_PROJECTS"] = projects
        current = lambda conv: page_data(run("build", "--current", conv, "--cache", self.cache)[1]["page"])[1]["current"]
        self.assertEqual(current(S1), S1)
        self.assertEqual(current(X), S1)        # the link's conversation: the one the user came from keeps the dot
        self.assertEqual(current(S2), S2)       # a conversation of its own takes it
        self.assertEqual(current(X), S2)

    def test_a_run_also_summarizes_the_other_sessions(self):
        """The first pass of a run lists the project's other sessions that need a summary; the model writes one sentence
        each from `show others`, apply records them with the run's own, and the page shows them. A later run of another
        session finds nothing left to summarize."""
        code, out = run("prepare", *self.common)
        self.assertEqual(out["others"], 2)
        code, text = run("show", "others", *self.common)
        self.assertEqual(code, 0)
        self.assertIn("[session 0a182a7b]\ntitle: release 0.3.0", text)
        self.assertIn("[session fd14e71a]", text)
        self.assertNotIn("[session 953c0ab1]", text)
        with open(os.path.join(ROOT, "fixtures", "extract", "tidepool-1.json"), encoding="utf-8") as f:
            ext = json.load(f)
        ext["others"] = [{"session": "0a182a7b", "gist": "You released 0.3.0."}, {"session": "fd14e71a", "gist": "You pinned CI to 3.12."}]
        with open(out["extract"], "w", encoding="utf-8") as f:
            json.dump(ext, f)
        code, res = run("apply", *self.common)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["summaries"], 3)
        self.assertFalse(os.path.exists(out["extract"].replace(".extract.json", ".others.txt")))
        run("build", "--done", "--session", S1, *self.common)
        code, b = run("build", *self.common)
        html, data = page_data(b["page"])
        self.assertEqual({s["id"][:8]: s.get("summary") for s in data["sessions"]},
                         {"953c0ab1": ext["gist"], "0a182a7b": "You released 0.3.0.", "fd14e71a": "You pinned CI to 3.12."})
        code, again = run("prepare", "--session", S2, *self.common)
        self.assertEqual(again["others"], 0)
        code, res = run("show", "others", "--session", S2, *self.common)
        self.assertEqual((code, res["ok"]), (1, False))

    def test_the_excerpts_are_read_in_parts_and_apply_needs_no_mark(self):
        """Excerpts of other sessions come in parts like the digest (a long Bash result is saved to a file instead of
        shown), and apply takes the summaries even when the run's mark has expired meanwhile."""
        with mock.patch.object(treesight, "PART_BYTES", 1000):      # each excerpt fits, both do not
            code, out = run("prepare", *self.common)
            self.assertEqual(out["others_parts"], 2)
            code, one = run("show", "others", "--part", "1", *self.common)
            code, two = run("show", "others", "--part", "2", *self.common)
        self.assertTrue(one.startswith("[session fd14e71a]") and one.endswith("[end of part 1 of 2; read part 2 next]"), one)
        self.assertTrue(two.startswith("[session 0a182a7b]") and two.endswith("that was the last part]"), two)
        os.remove(treesight._job_path(self.cache, PROJECT, S1))         # the mark expired
        with open(os.path.join(ROOT, "fixtures", "extract", "tidepool-1.json"), encoding="utf-8") as f:
            ext = dict(json.load(f), others=[{"session": "fd14e71a", "gist": "You pinned CI to 3.12."}])
        with open(out["extract"], "w", encoding="utf-8") as f:
            json.dump(ext, f)
        code, res = run("apply", *self.common)
        self.assertTrue(res["ok"], res)
        self.assertEqual(ledger.load(PROJECT)["sessions"]["fd14e71a-3afc-5d70-9e9a-cd1e6396b471"]["gist"]["text"], "You pinned CI to 3.12.")

    def test_a_run_started_from_the_page_does_not_open_it_again(self):
        """The page's own links add --no-open: the page is open, so the new conversation's builds update it."""
        asked = []
        real, build.open_page = build.open_page, lambda res: asked.append(res["page"]) or res.update(browser_asked=True) or res
        try:
            code, out = run("prepare", "--session", "0a182a7b --no-open", "--current", S2, "--cache", self.cache)
            self.assertEqual(out["session"], S2)
            code, b = run("build", "--open", "--session", S2, "--current", S2, "--cache", self.cache)
        finally:
            build.open_page = real
        self.assertEqual((asked, b["browser_asked"], b["open_page_updates"]), ([], False, True))

    def test_a_folder_whose_name_is_masked_gets_no_links(self):
        """A part of the project's folder name that looks like an address is masked on the page, its name included,
        and the page is told so: a link or command with the masked folder would point nowhere."""
        projects = os.path.join(self.tmp, "projects")
        folder = os.path.join(projects, PROJECT)
        shutil.copytree(os.path.join(ROOT, "fixtures", "projects", PROJECT), folder)
        for name in os.listdir(folder):
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                text = f.read()
            with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
                f.write(text.replace('"cwd": "/home/dev/tidepool"', '"cwd": "/home/dev/vm-192.0.2.7"'))
        os.environ["TREESIGHT_PROJECTS"] = projects
        code, b = run("build", *self.common)
        html, data = page_data(b["page"])
        self.assertEqual({k: data["project"][k] for k in ("path", "name", "masked")}, {"path": "/home/dev/vm-x.x.x.x", "name": "vm-x.x.x.x", "masked": True})
        self.assertIn("if(D.project.masked){acts.append(copyBtn(W.copyDraw,draw));return box}", html)

    def test_running_treesight_does_not_make_a_session_look_changed(self):
        """A session's /treesight command and its notice come after what the session said: its summary is not
        rewritten on every run just because of them."""
        folder = os.path.join(self.tmp, "proj")
        shutil.copytree(os.path.join(ROOT, "fixtures", "projects", PROJECT), folder)
        fd = "fd14e71a-3afc-5d70-9e9a-cd1e6396b471"
        path = os.path.join(folder, fd + ".jsonl")
        meta, entries = treesight.transcript.read_session(path)
        upto = treesight.said_last(meta, entries)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "uuid": "aaaaaaaa-0000-4000-8000-000000000001", "sessionId": fd, "cwd": "/home/dev/tidepool",
                                "timestamp": "2026-10-09T09:00:00.000Z", "origin": {"kind": "human"},
                                "message": {"role": "user", "content": "/treesight:treesight"}}) + "\n")
        self.assertEqual(treesight.said_last(*treesight.transcript.read_session(path)), upto)
        need = lambda gist: [m["id"][:8] for m, _ in treesight.to_summarize(folder, {"sessions": {fd: {"runs": 0, "gist": gist}}}, S1)]
        self.assertNotIn("fd14e71a", need({"upto": upto}))
        self.assertIn("fd14e71a", need({"upto": "2026-01-01T00:00:00Z"}))
        self.assertIn("fd14e71a", need({"upto": None}))       # a summary without a time is redone, not a crash

    def test_which_sessions_need_a_summary(self):
        """A session without a tree whose summary is missing or older than its last message, or a drawn session with
        none (its own run writes it from the whole session); never the session being drawn; the most recent first,
        at most OTHERS_MAX."""
        folder = os.path.join(ROOT, "fixtures", "projects", PROJECT)
        fd = "fd14e71a-3afc-5d70-9e9a-cd1e6396b471"
        last = {m["id"]: m["last_at"] for m in build.sessions_in(folder)}
        need = lambda sessions: [m["id"][:8] for m, _ in treesight.to_summarize(folder, {"sessions": sessions}, S1)]
        self.assertEqual(need({}), ["fd14e71a", "0a182a7b"])
        self.assertEqual(need({fd: {"runs": 0, "gist": {"upto": last[fd]}}}), ["0a182a7b"])
        self.assertEqual(need({fd: {"runs": 0, "gist": {"upto": "2026-01-01T00:00:00Z"}}}), ["fd14e71a", "0a182a7b"])
        self.assertEqual(need({S2: {"runs": 1, "gist": {"upto": "2026-01-01T00:00:00Z"}}}), ["fd14e71a"])
        self.assertEqual(need({S2: {"runs": 1, "gist": None}}), ["fd14e71a", "0a182a7b"])
        with mock.patch.object(treesight, "OTHERS_MAX", 1):
            self.assertEqual(need({}), ["fd14e71a"])

    def test_sessions_run_with_claude_p_are_left_off_the_page(self):
        """A session made by claude -p (a script, a test) is not listed, the page says how many were left out, and no run
        is asked to summarize it."""
        projects = os.path.join(self.tmp, "projects")
        folder = os.path.join(projects, PROJECT)
        shutil.copytree(os.path.join(ROOT, "fixtures", "projects", PROJECT), folder)
        quiet = "5d0e1f2a-3b4c-4d5e-8f6a-7b8c9d0e1f2a"
        with open(os.path.join(folder, "fd14e71a-3afc-5d70-9e9a-cd1e6396b471.jsonl"), encoding="utf-8") as f:
            recs = [json.loads(line) for line in f if line.strip()]
        with open(os.path.join(folder, quiet + ".jsonl"), "w", encoding="utf-8") as f:
            for r in recs:
                if "sessionId" in r:
                    r["sessionId"] = quiet
                if r.get("type") == "user":
                    r["entrypoint"] = "sdk-cli"
                f.write(json.dumps(r) + "\n")
        os.environ["TREESIGHT_PROJECTS"] = projects
        code, b = run("build", *self.common)
        html, data = page_data(b["page"])
        self.assertEqual(data["hidden"], 1)
        self.assertNotIn(quiet, [s["id"] for s in data["sessions"]])
        self.assertEqual(len(data["sessions"]), 3)
        self.assertNotIn(quiet[:8], [m["id"][:8] for m, _ in treesight.to_summarize(folder, {"sessions": {}}, S1)])
        code, out = run("prepare", "--session", quiet[:8], *self.common)       # once drawn, it is listed like any other
        with open(out["extract"], "w", encoding="utf-8") as f:
            json.dump(empty_extract(out["extract"].replace(".extract.json", ".digest.txt")), f)
        self.assertTrue(run("apply", "--session", quiet[:8], *self.common)[1]["ok"])
        code, b = run("build", *self.common)
        html, data = page_data(b["page"])
        self.assertIn(quiet, [s["id"] for s in data["sessions"]])
        self.assertNotIn("hidden", data)

    def test_the_browser_is_asked_once_per_conversation(self):
        """Later runs and corrections in the same conversation update the page that is already open (it reads its
        stamp) instead of opening another tab; another conversation opens it again."""
        asked = []
        real, build.open_page = build.open_page, lambda res: asked.append(res["page"]) or res.update(browser_asked=True) or res
        try:
            code, first = run("build", "--open", *self.common)
            code, again = run("build", "--open", *self.common)
            code, other = run("build", "--open", "--current", S2, "--cache", self.cache)
        finally:
            build.open_page = real
        self.assertEqual(len(asked), 2)
        self.assertEqual((first["browser_asked"], again["browser_asked"], again.get("open_page_updates"), other["browser_asked"]), (True, False, True, True))
        self.assertTrue(first["url"].startswith("file:///") and first["url"].endswith(".html"))
        # a conversation resumed after a long pause gets the page again: its tab is likely gone
        path = os.path.join(self.cache, "opened", PROJECT + ".json")
        with open(path, encoding="utf-8") as f:
            seen = json.load(f)
        seen[S1] -= treesight.OPEN_KEEP_S + 1
        with open(path, "w", encoding="utf-8") as f:
            json.dump(seen, f)
        build.open_page = lambda res: asked.append(res["page"]) or res.update(browser_asked=True) or res
        try:
            code, later = run("build", "--open", *self.common)
        finally:
            build.open_page = real
        self.assertEqual((later["browser_asked"], len(asked)), (True, 3))

    def test_titles_are_matched_as_written(self):
        """Scrubbing is for showing a title: words such as an address or a key name in it still find the session."""
        projects = os.path.join(self.tmp, "projects")
        shutil.copytree(os.environ["TREESIGHT_PROJECTS"], projects)
        os.environ["TREESIGHT_PROJECTS"] = projects
        with open(os.path.join(projects, PROJECT, S2 + ".jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "custom-title", "customTitle": "Deploy to 192.0.2.5 and rotate api_key: staging2026x"}) + "\n")
        self.assertIn(S2, treesight.find_session("deploy to 192.0.2.5", S1))
        self.assertIn(S2, treesight.find_session("rotate api_key", S1))

    def test_a_run_the_user_stopped_can_be_restarted(self):
        code, out = run("prepare", *self.common)
        code, busy = run("prepare", *self.common)
        self.assertTrue(busy["busy"])
        self.assertGreaterEqual(busy["free_in_min"], 20)          # when it would count as stopped by itself
        code, again = run("prepare", "--restart", *self.common)
        self.assertEqual((code, again.get("busy"), again["pass_number"]), (0, None, 1), again)
        code, again = run("prepare", "--session", S1[:8] + " --restart", *self.common)   # the flag left among the words
        self.assertEqual((code, again.get("busy")), (0, None), again)

    def test_wrong_arguments_come_back_as_json(self):
        code, out = run("edit", "hide", *self.common)               # no item named
        self.assertEqual((code, out["ok"]), (1, False), out)
        code, out = run("prepare", "--no-such-flag", *self.common)
        self.assertEqual((code, out["ok"]), (1, False), out)

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
        # sizes are bytes: Claude Code saved a 20,000-character part of mostly Chinese text (34,858 bytes) to a file
        # instead of showing it, so the model had to read it back with a tool it was not pre-approved for
        zh = "[reply 2026-09-14T09:00:00.000Z 00000001-0000-4000-8000-000000000000]\n" + ("读完了整个会话。\n" * 3000)
        parts = treesight.split_parts(zh, 24000)
        self.assertEqual("".join(parts), zh)
        self.assertTrue(all(len(p.encode("utf-8")) <= 24000 for p in parts))
        self.assertTrue(all(p.endswith("\n") for p in parts))      # still broken at lines

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
        self.assertIn("\u201cPyPI token from org admin\u201d", e["error"])   # by the labels the page shows, not by ids
        code, e = run("edit", "set", "PyCon proposal", "--field", "blocked_by=token PyPI", *self.common)    # words in any order
        self.assertEqual((code, e["fields"]), (0, {"blocked_by": ledger.load(PROJECT)["open"][2]["id"]}), e)
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
        self.assertEqual(stamp(page), {"v": d["version"], "focus": S2, "pending": True})   # an open page sees the run start
        self.assertEqual(d["focus"], S2)
        code, _ = run("build", "--done", "--session", S2, *self.common)
        html, d = page_data(page)
        self.assertNotIn("pending", d)
        self.assertEqual(stamp(page), {"v": d["version"], "focus": S2, "pending": False})  # and end

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
        self.assertFalse(stamp(glob.glob(os.path.join(self.cache, "pages", "*.html"))[0])["pending"])

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
        self.assertFalse(stamp(glob.glob(os.path.join(self.cache, "pages", "*.html"))[0])["pending"])
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

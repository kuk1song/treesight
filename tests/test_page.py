"""The page build: escaping, the CSP hash, the public-page guard, colours in step with dev/palettes.json, and the sample projects.
Run: python3 -m unittest discover -s tests"""
import base64
import contextlib
import glob
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "dev"))

import build  # noqa: E402
import ledger  # noqa: E402
import transcript  # noqa: E402
import treesight  # noqa: E402
from palcheck import cr  # noqa: E402

FOLDER = os.path.join(ROOT, "fixtures", "projects", "-home-dev-tidepool")


def data_block(html):
    return json.loads(re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S).group(1))


class Render(unittest.TestCase):
    base = {"schema": "treesight/page@1", "asof": "2026-09-24T09:00:00Z", "current": None, "project": {"path": "/p", "name": "p"}, "sessions": []}

    def test_script_end_in_data_cannot_break_out(self):
        evil = "</script><script>alert(1)</script> & <!--  "
        html = build.render(dict(self.base, project={"path": evil, "name": "p"}))
        self.assertNotIn("</script><script>alert", html)
        self.assertEqual(data_block(html)["project"]["path"], evil)
        self.assertEqual(len(re.findall(r"<script>", html)), 1)

    def test_csp_allows_exactly_the_page_script(self):
        html = build.render(self.base)
        script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
        want = "sha256-" + base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode()
        csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html).group(1)
        self.assertIn("default-src 'none'", csp)
        self.assertIn("script-src '%s'" % want, csp)
        self.assertNotIn("__", csp)

    def test_a_local_page_may_load_its_stamp_and_a_published_one_loads_nothing(self):
        """A page on the user's machine keeps itself current by loading the stamp next to it, so its policy lets its own
        script insert another; a published page allows only its own script. Neither reloads on a timer."""
        csp = lambda html: re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html).group(1)
        pending = build.render(dict(self.base, live=True, version="0123", pending=[{"session": "x", "title": "t", "estimate_s": 150},
                                                                                 {"session": "y", "title": "u", "estimate_s": 90}]))
        self.assertIn("'strict-dynamic'", csp(pending))         # only what the hashed script itself inserts
        self.assertNotIn("'self'", csp(pending))
        self.assertEqual([p["estimate_s"] for p in data_block(pending)["pending"]], [150, 90])
        self.assertNotIn("'strict-dynamic'", csp(build.render(self.base)))
        for html in (pending, build.render(self.base)):
            self.assertNotIn('http-equiv="refresh"', html)

    def test_public_guard(self):
        build.assert_public("version 2.1.288 and x.x.x.x are fine")
        for bad in ("host 203.0.113.12", "mail a@example.org"):   # documentation addresses (RFC 5737, RFC 2606)
            with self.assertRaises(ValueError):
                build.assert_public(bad)

    def test_the_browser_is_asked_with_open_a_on_macos_and_browser_is_honoured(self):
        found = subprocess.CompletedProcess([], 0, stdout="/Applications/Some Browser.app\n")
        with mock.patch.dict(os.environ, {}, clear=False), mock.patch.object(build.sys, "platform", "darwin"), \
                mock.patch.object(build.subprocess, "run", return_value=found):
            os.environ.pop("BROWSER", None)
            self.assertEqual(build._browser_command("/p/x.html"), ["open", "-a", "/Applications/Some Browser.app", "/p/x.html"])
        with mock.patch.dict(os.environ, {}, clear=False), mock.patch.object(build.sys, "platform", "darwin"), \
                mock.patch.object(build.subprocess, "run", side_effect=OSError):
            os.environ.pop("BROWSER", None)
            self.assertEqual(build._browser_command("/p/x.html"), ["open", "/p/x.html"])     # no default browser found
        with mock.patch.dict(os.environ, {"BROWSER": "true"}), mock.patch.object(build.webbrowser, "open", return_value=True) as wb:
            self.assertIsNone(build._browser_command("/p/x.html"))
            self.assertEqual(build.open_page({"page": "/p/x.html"})["browser_asked"], True)
            wb.assert_called_once_with("file:///p/x.html")
        with mock.patch.object(build.sys, "platform", "linux"), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BROWSER", None)
            self.assertIsNone(build._browser_command("/p/x.html"))

    def test_page_has_no_network_reference(self):
        with open(build.TEMPLATE, encoding="utf-8") as f:
            html = f.read()
        self.assertFalse(re.search(r"""(?:src|href)=["']https?:""", html))
        self.assertNotIn("fetch(", html)
        self.assertNotIn("XMLHttpRequest", html)

    def test_script_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        script = re.search(r"<script>(.*?)</script>", build.render(self.base), re.S).group(1)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(script)
        try:
            r = subprocess.run([node, "--check", f.name], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        finally:
            os.unlink(f.name)

    def test_the_interface_language_is_the_first_preferred_one_the_page_has(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        with open(build.TEMPLATE, encoding="utf-8") as f:
            html = f.read()
        pick = re.search(r"^const LANGS=.*\n^const ZH=.*$", html, re.M).group(0)
        cases = {"en-US": False, "zh-CN": True, "ja,zh-CN,en": True, "ja,en,zh-CN": False, "zh-TW,en": True,
                 "fr,de": False, "en-GB,zh-CN": False, "": False}
        script = "".join("{const navigator={languages:%s,language:%s};%s;console.log(ZH)}" % (
            json.dumps(k.split(",") if k else []), json.dumps(k.split(",")[0]), pick) for k in cases)
        r = subprocess.run([node, "-e", script], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split(), [str(v).lower() for v in cases.values()])

    def test_a_sample_counts_days_to_its_own_date(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        with open(build.TEMPLATE, encoding="utf-8") as f:
            html = f.read()
        time = html[html.index("/* ---------- time"):html.index("/* an item marked no longer possible")]
        script = "".join("{const D=%s;%s;console.log(ago('2026-09-20'))}" % (json.dumps(d), time)
                         for d in ({"today": "2026-10-03T09:00:00Z"}, {}))
        r = subprocess.run([node, "-e", script], capture_output=True, text=True, env=dict(os.environ, TZ="UTC"))
        self.assertEqual(r.returncode, 0, r.stderr)
        fixed, live = r.stdout.split()
        self.assertEqual(fixed, "13")
        self.assertGreater(int(live), 13)            # without a date of its own, the page counts to the viewer's today

    def test_chinese_puts_a_space_before_a_latin_name(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        with open(build.TEMPLATE, encoding="utf-8") as f:
            html = f.read()
        fn = re.search(r"waitingOn:(x=>'在等'[^,]*),", html).group(1)
        r = subprocess.run([node, "-e", "const f=%s;console.log(JSON.stringify(['Alex','Émile','老周','3 号'].map(f)))" % fn], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), ["在等 Alex", "在等 Émile", "在等老周", "在等 3 号"])

    def test_links_open_claude_code_with_the_command_typed_in(self):
        """A session without a tree links to claude-cli://open with the project folder and the command, both encoded
        (https://code.claude.com/docs/en/deep-links); the command to copy names the folder as one types it."""
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        with open(build.TEMPLATE, encoding="utf-8") as f:
            html = f.read()
        defs = "\n".join(re.search(r"^const %s=.*;$" % name, html, re.M).group(0) for name in ("shq", "deep", "typed"))
        script = ("const D={project:{path:'/Users/me/recipe-box'}};%s\nconsole.log(JSON.stringify([deep('/resume abc'),"
                  "deep('/treesight:treesight 0a182a7b'),typed('/Users/me/recipe-box'),typed('/home/dev/tide pool'),"
                  "typed('/opt/work'),shq(\"it's\")]))" % defs)
        r = subprocess.run([node, "-e", script], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), [
            "claude-cli://open?cwd=%2FUsers%2Fme%2Frecipe-box&q=%2Fresume%20abc",
            "claude-cli://open?cwd=%2FUsers%2Fme%2Frecipe-box&q=%2Ftreesight%3Atreesight%200a182a7b",
            "~/recipe-box", "'/home/dev/tide pool'", "/opt/work", "'it'\\''s'"])

    def test_growth_also_while_drawing_and_once_seen(self):
        """The tree grows on a page opened while a run is drawing (it stood still there since 0.1.0, from when such a
        page reloaded every 20 s), and a tab opened in the background grows when it is first shown, not out of sight."""
        with open(build.TEMPLATE, encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("D.pending", html.split("const RM=", 1)[1].split(";", 1)[0])
        self.assertIn("whenSeen(()=>run(first?1000:600))", html)

    def test_an_open_node_keeps_its_sentence(self):
        """A node's card shows its sentence on hover and is hidden once the node is open, so the open node must show the
        sentence itself: #17 hid it there whenever a mouse was in use. dev/check_live.mjs checks this with a mouse."""
        with open(build.TEMPLATE, encoding="utf-8") as f:
            css = f.read().split("</style>", 1)[0]
        self.assertIn(".node.open>.card{display:none}", css)
        self.assertNotRegex(css, r"\.(?:ln|lt|dup)\b[^{}]*\{[^}]*display:none")       # a rule that hides the sentence

    def test_english_counts_one_day(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        with open(build.TEMPLATE, encoding="utf-8") as f:
            html = f.read()
        fn = re.findall(r"day:(n=>[^,]*?(?:\([^)]*\))?[^,]*?),storyHint", html)[1]     # the second W is the English one
        r = subprocess.run([node, "-e", "const f=%s;console.log(JSON.stringify([1,2].map(f)))" % fn], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), ["1 day", "2 days"])

    def test_a_due_date_still_ahead_is_shown(self):
        """Items with a due date still ahead had no section and no date of their own: they were listed under
        "No time set", so a due date set with `set` showed nothing until it had passed."""
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        with open(build.TEMPLATE, encoding="utf-8") as f:
            html = f.read()
        code = html[html.index("/* ---------- time"):html.index("/* ---------- data")]
        words = re.findall(r"due:(\(d,n\)=>[^,]*?'[^']*'\+d\+'[^']*'\+n\+'[^']*'[^,]*?(?:\([^)]*\))?[^,]*?),confirm", html)
        self.assertEqual(len(words), 2)
        items = [{"id": "a", "label": "later", "due": "2026-11-05"}, {"id": "b", "label": "sooner", "due": "2026-10-25", "when": "after the trip"},
                 {"id": "c", "label": "past", "due": "2026-10-01"}, {"id": "d", "label": "trip", "when": "after the trip"},
                 {"id": "e", "label": "none"}, {"id": "f", "label": "today", "due": "2026-10-21"}]
        script = ("const D={today:'2026-10-21T09:00:00Z'};const W={bBoth:'both',bOverdue:'overdue',bStale:'stale',bConfirm:'confirm',"
                  "bDue:'due',bNoTime:'none'};%s;const zh=%s,en=%s;"
                  "console.log(JSON.stringify([sections(%s).map(b=>[b[0],b[1].map(x=>x.id)]),[zh('11-05',15),zh('10-21',0),en('11-05',15),en('10-22',1)]]))"
                  % (code, words[0], words[1], json.dumps(items)))
        r = subprocess.run([node, "-e", script], capture_output=True, text=True, env=dict(os.environ, TZ="UTC"))
        self.assertEqual(r.returncode, 0, r.stderr)
        got, texts = json.loads(r.stdout)
        self.assertEqual(got, [["overdue", ["c"]], ["due", ["f", "b", "a"]], ["after the trip", ["d"]], ["none", ["e"]]])
        self.assertEqual(texts, ["截止 11-05 · 还有 15 天", "今天截止", "Due 11-05 · in 15 days", "Due 10-22 · in 1 day"])

    def test_long_words_wrap_everywhere_text_is_shown(self):
        """Labels, open items, hover cards and expanded nodes (line, twigs, story and source) wrap long file names."""
        with open(build.TEMPLATE, encoding="utf-8") as f:
            css = f.read().split("</style>")[0]
        wrapped = set()
        for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
            if "overflow-wrap:anywhere" in body:
                wrapped |= {x.strip() for x in sel.split(",")}
        self.assertLessEqual({".where b", ".node .lb", ".oi", ".card", ".more"}, wrapped)

    def test_chinese_sentences_and_day_counts(self):
        """Full stops at the end of Chinese sentences, and 已过 for the days an item has waited or been put off."""
        with open(build.TEMPLATE, encoding="utf-8") as f:
            html = f.read()
        zh = html[html.index("const W=ZH?{"):html.index("}:{", html.index("const W=ZH?{"))]
        for key in ("noSummary", "gone", "pendingLate"):
            self.assertRegex(zh, r"%s:[^\n]*?。'" % key, key)
        self.assertIn("已过 '+n+' 天", zh)
        self.assertNotIn("已等", zh)

    def test_every_view_runs_without_script_errors(self):
        """Every view and every click handler of a real page, in a real browser: the tests above check pieces of the
        script, this catches what only shows when it runs (a name moved out of a function's scope did once)."""
        sys.path.insert(0, os.path.join(ROOT, "dev"))
        import check_page
        if not check_page.browser():
            self.skipTest("no headless Chromium")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = check_page.main()
        if code == 2 and not os.environ.get("CI"):        # on CI a browser was found, so an unreadable console is a failure
            self.skipTest("the browser's console cannot be read")
        self.assertEqual(code, 0, out.getvalue())

    def test_an_open_page_follows_corrections_and_runs(self):
        """No new tab after the first: the open page reloads itself from its stamp (dev/check_live.mjs drives it)."""
        sys.path.insert(0, os.path.join(ROOT, "dev"))
        import check_page
        node, ch = shutil.which("node"), check_page.browser()
        if not node or not ch:
            self.skipTest("needs node and a headless Chromium")
        major = int(subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v").split(".")[0])
        if major < 22:
            self.skipTest("needs Node 22 or later, for its WebSocket")
        r = subprocess.run([node, os.path.join(ROOT, "dev", "check_live.mjs"), ch], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_page_states_the_scripts_numbers(self):
        """How often the page reads its stamp, and when a run seems to have stopped: those numbers live in the scripts."""
        with open(build.TEMPLATE, encoding="utf-8") as f:
            html = f.read()
        self.assertIn("STAMP=[%d,%d]" % build.STAMP_S, html)
        self.assertIn("+%d)*1000" % treesight.JOB_GRACE_S, html)

    def test_both_languages_have_the_same_words(self):
        with open(build.TEMPLATE, encoding="utf-8") as f:
            html = f.read()
        body = html[html.index("const W=ZH?{"):html.index("/* ---------- time")]
        zh, en = body.split("}:{", 1)
        keys = lambda s: set(re.findall(r"(?:^\s*|[{,]\s*)([A-Za-z]+):", s))
        self.assertEqual(keys(zh), keys(en))


class Kept(unittest.TestCase):
    """A session whose transcript Claude Code has deleted is drawn from what the ledger kept."""
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="treesight-kept-")
        os.environ["TREESIGHT_HOME"] = self.home
        self.path = glob.glob(os.path.join(FOLDER, "953c0ab1-*.jsonl"))[0]
        with open(os.path.join(ROOT, "fixtures", "extract", "tidepool-1.json"), encoding="utf-8") as f:
            self.ext = json.load(f)
        self.gone = os.path.join(self.home, "transcripts", "-home-dev-tidepool")   # the project folder, emptied by a cleanup
        os.makedirs(self.gone)

    def tearDown(self):
        os.environ.pop("TREESIGHT_HOME", None)
        shutil.rmtree(self.home)

    def test_drawn_from_the_ledger(self):
        meta, entries = transcript.read_session(self.path)
        probs, _ = ledger.apply(self.ext, transcript.digest(self.path), "-home-dev-tidepool", meta=treesight.session_meta(meta, entries))
        self.assertEqual(probs, [])
        d = build.page_data(self.gone)
        self.assertEqual(len(d["sessions"]), 1)
        s = d["sessions"][0]
        self.assertTrue(s["gone"] and s["generated"])
        self.assertEqual((s["title"], s["first_at"], s["prompts"]), (meta["title"], meta["first_at"], meta["prompts"]))
        self.assertEqual((len(s["nodes"]), len(s["open"])), (len(self.ext["nodes"]), len(self.ext["open"])))
        self.assertEqual(d["project"]["path"], meta["cwd"])
        self.assertNotIn("gone", build.page_data(FOLDER)["sessions"][0])

    def test_kept_times_skip_dates_without_a_time(self):
        """Ledgers from before 2026-10-16 keep no session metadata; an item raised on a date alone must not become first_at."""
        led = {"meta": {}, "nodes": [], "last_run": {"at": "2026-10-01T08:00:00Z"}}
        state = {"open": [{"session": "s", "raised_at": "2026-09-14"}, {"session": "s", "raised_at": "2026-09-20T10:00:00Z"}]}
        m = build._kept_meta("s", led, state)
        self.assertEqual((m["first_at"], m["last_at"]), ("2026-09-20T10:00:00Z", "2026-09-20T10:00:00Z"))

    def test_a_long_title_with_addresses_still_builds(self):
        """A mask can be longer than what it hides, so a title is scrubbed before it is cut to length."""
        src = glob.glob(os.path.join(FOLDER, "fd14e71a-*.jsonl"))[0]
        dst = os.path.join(self.gone, os.path.basename(src))
        shutil.copy(src, dst)
        with open(dst, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "custom-title", "customTitle": "write to " + "a@b.co " * 32, "sessionId": os.path.basename(src)[:-6]}) + "\n")
        t = build.page_data(self.gone)["sessions"][0]["title"]
        self.assertLessEqual(len(t), 200)
        self.assertIn("[email]", t)

    def test_a_session_on_disk_without_prompts_is_not_called_gone(self):
        meta, entries = transcript.read_session(self.path)
        ledger.apply(self.ext, transcript.digest(self.path), "-home-dev-tidepool", meta=treesight.session_meta(meta, entries))
        with open(self.path, encoding="utf-8") as f:
            recs = [json.loads(l) for l in f]
        with open(os.path.join(self.gone, os.path.basename(self.path)), "w", encoding="utf-8") as f:
            for r in recs:   # the same session with every prompt turned into a /treesight command
                if r.get("type") == "user" and (r.get("origin") or {}).get("kind") == "human":
                    r = dict(r, message={"role": "user", "content": "/treesight:treesight"})
                f.write(json.dumps(r) + "\n")
        s = build.page_data(self.gone)["sessions"][0]
        self.assertNotIn("gone", s)
        self.assertEqual(len(s["nodes"]), len(self.ext["nodes"]))

    def test_ledgers_without_metadata_still_build(self):
        ledger.apply(self.ext, transcript.digest(self.path), "-home-dev-tidepool")
        s = build.page_data(self.gone)["sessions"][0]
        self.assertEqual((s["title"], s["gone"]), (self.ext["session"][:8], True))


class Palette(unittest.TestCase):
    def test_template_colours_match_palettes_json(self):
        with open(os.path.join(ROOT, "dev", "palettes.json"), encoding="utf-8") as f:
            dark = json.load(f)["schemes"]["default"]["dark"]
        with open(build.TEMPLATE, encoding="utf-8") as f:
            root = re.search(r":root\{(.*?)\}", f.read(), re.S).group(1)
        css = dict(re.findall(r"--([a-z0-9-]+):(#[0-9A-Fa-f]{6})", root))
        for k, v in dark.items():
            self.assertEqual(css.get(k.replace("_", "-"), "").upper(), v.upper(), k)
        # a hollow ring when the colour stands out on its own, as the v15 build decided
        self.assertGreaterEqual(cr(dark["waiting"], dark["bg"]), 3)
        self.assertEqual(css["waiting-ring"].upper(), dark["waiting"].upper())


class Sample(unittest.TestCase):
    def build(self, sample):
        out = tempfile.mkdtemp(prefix="treesight-page-")
        try:
            r = subprocess.run([sys.executable, os.path.join(ROOT, "dev", "make_sample.py"), "--sample", sample, "--out", os.path.join(out, "demo.html")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(os.path.join(out, "demo.html"), encoding="utf-8") as f:
                return data_block(f.read())
        finally:
            shutil.rmtree(out)

    def test_demo_page(self):
        """The README demo, a made-up web-app project: done and found nodes, one that got stuck, and open items in each group the drawer has."""
        d = self.build("recipe-box")
        self.assertEqual(d["today"], d["asof"])          # day counts run to the sample's own date
        s = {x["id"][:8]: x for x in d["sessions"]}
        self.assertEqual(sorted(s), ["0c0f810a", "0c4f931d", "12517ac7"])
        self.assertFalse(s["12517ac7"]["generated"])
        self.assertEqual(d["current"][:8], "0c0f810a")
        first = s["0c4f931d"]
        self.assertEqual(sorted(n["kind"] for n in first["nodes"]), ["done", "done", "done", "found"])
        self.assertEqual(sum(1 for n in first["nodes"] if n.get("story")), 1)
        self.assertEqual(sorted(o["state"] for o in first["open"]), ["confirm", "open", "open", "stale"])
        self.assertEqual((s["0c0f810a"]["last_run"]["closed"], s["0c0f810a"]["last_run"]["flagged"]), (2, 2))

    def test_demo_page_in_chinese(self):
        """The same story written in Chinese, for the Chinese README's video: same shape, Chinese text."""
        d = self.build("recipe-box-zh")
        s = {x["id"][:8]: x for x in d["sessions"]}
        self.assertEqual(sorted(s), ["706417bf", "e3b89c9b", "e704c371"])
        first = s["706417bf"]
        self.assertEqual(sorted(n["kind"] for n in first["nodes"]), ["done", "done", "done", "found"])
        self.assertEqual(sorted(o["state"] for o in first["open"]), ["confirm", "open", "open", "stale"])
        self.assertEqual((s["e3b89c9b"]["last_run"]["closed"], s["e3b89c9b"]["last_run"]["flagged"]), (2, 2))
        self.assertTrue(all(re.search("[\u4e00-\u9fff]", n["label"]) for n in first["nodes"]))

    def test_sample_page(self):
        d = self.build("tidepool")
        self.assertEqual(d["today"], "2026-09-24T09:00:00Z")
        s = {x["id"][:8]: x for x in d["sessions"]}
        self.assertEqual(sorted(s), ["0a182a7b", "953c0ab1", "fd14e71a"])
        self.assertTrue(s["953c0ab1"]["generated"] and s["0a182a7b"]["generated"])
        self.assertFalse(s["fd14e71a"]["generated"])
        self.assertTrue(s["0a182a7b"]["custom_title"])
        states = sorted(o["state"] for o in s["953c0ab1"]["open"])
        self.assertEqual(states, ["confirm", "open", "stale", "stale"])
        self.assertEqual(d["current"][:8], "0a182a7b")
        self.assertEqual((s["0a182a7b"]["last_run"]["closed"], s["0a182a7b"]["last_run"]["flagged"]), (2, 3))
        self.assertEqual(d["project"]["first_at"], s["953c0ab1"]["first_at"])


if __name__ == "__main__":
    unittest.main()

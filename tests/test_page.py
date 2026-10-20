"""The page build: escaping, the CSP hash, the public-page guard, colours in step with dev/palettes.json, and the sample project.
Run: python3 -m unittest discover -s tests"""
import base64
import glob
import hashlib
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

    def test_pending_page_reloads_and_finished_page_does_not(self):
        pending = build.render(dict(self.base, pending=[{"session": "x", "title": "t", "estimate_s": 150}, {"session": "y", "title": "u", "estimate_s": 90}]))
        self.assertIn('<meta http-equiv="refresh" content="20">', pending)
        self.assertEqual([p["estimate_s"] for p in data_block(pending)["pending"]], [150, 90])
        self.assertNotIn('http-equiv="refresh"', build.render(self.base))

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
        """The README demo: every kind of node and open item the page can show, in a made-up web-app project."""
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

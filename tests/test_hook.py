"""scripts/notice_hook.py and hooks/hooks.json: the plugin's hook asks the main conversation to show a finished run's
report as it is, and lets every other prompt through untouched. Run: python3 -m unittest discover -s tests"""
import json
import os
import statistics
import subprocess
import sys
import time
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import notice_hook  # noqa: E402
import treesight  # noqa: E402

HOOK = os.path.join(ROOT, "scripts", "notice_hook.py")
REPORT = treesight.REPORT_HEAD + "\n\n🌳 treesight：「发布 0.3.0」的树已生成，新增 6 个节点、14 件待完成。\n页面已更新：file:///home/dev/p.html"


def notice(result=REPORT, agent="/treesight:treesight", status="completed"):
    """A completion notice in the form Claude Code 2.1.299 writes into the transcript (made-up ids and numbers)."""
    return ("<task-notification>\n<task-id>a0f1c2d3e4b5a6978</task-id>\n<output-file>/tmp/x/tasks/a0f1c2d3e4b5a6978.output</output-file>\n"
            "<status>%s</status>\n<summary>Agent \"%s\" finished</summary>\n<note>A task-notification fires each time this agent stops.</note>\n"
            "<result>%s</result>\n<usage><subagent_tokens>90000</subagent_tokens><tool_uses>10</tool_uses><duration_ms>300000</duration_ms></usage>\n"
            "</task-notification>" % (status, agent, result))


def hook(stdin, env=None):
    t = time.perf_counter()
    r = subprocess.run([sys.executable, "-I", "-S", HOOK], input=stdin if isinstance(stdin, bytes) else stdin.encode("utf-8"),
                       capture_output=True, env=env)
    return r, (time.perf_counter() - t) * 1000


class Answer(unittest.TestCase):
    def test_a_finished_run_is_shown_as_it_is(self):
        out = notice_hook.answer(notice())
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertNotIn("decision", out)      # never blocked: a block shows the user a warning (tested on 2026-10-26)
        body = ctx.split("<<<\n", 1)[1].split("\n>>>", 1)[0]
        self.assertEqual(body, REPORT.split("\n\n", 1)[1])
        self.assertNotIn(treesight.REPORT_HEAD, body)

    def test_a_run_named_with_words_is_shown_too(self):
        self.assertIsNotNone(notice_hook.answer(notice(agent="/treesight:treesight 0a182a7b")))
        self.assertIsNotNone(notice_hook.answer(notice(agent="/treesight release 0.3")))

    def test_everything_else_goes_through_untouched(self):
        for prompt in ["hello", "  ", "", REPORT,                                  # what the user types, even a pasted report
                       notice(status="failed"), notice(status="killed"),         # a run that did not finish: Claude may help
                       notice(agent="/other:skill"), notice(agent="/treesightx"),    # someone else's background work
                       notice(result="Done."), notice(result=treesight.REPORT_HEAD),   # not a report of this skill, or no lines
                       notice(result="x\n" + REPORT),
                       "Please look at this:\n" + notice()]:                       # a notice quoted in a prompt
            self.assertIsNone(notice_hook.answer(prompt), prompt[:60])


class Process(unittest.TestCase):
    def test_bad_input_never_stops_a_prompt(self):
        for stdin in [b"", b"not json", b"[1, 2]", b'{"prompt": null}', b'{"prompt": 3}', b"\xff\xfe\x00", json.dumps({"prompt": "hi"}).encode()]:
            r, _ = hook(stdin)
            self.assertEqual((r.returncode, r.stdout), (0, b""), stdin)

    def test_any_locale_reads_and_writes_chinese(self):
        """The hook reads bytes and writes ASCII JSON, so a POSIX locale changes nothing."""
        env = {k: v for k, v in os.environ.items() if not k.startswith(("LC_", "LANG", "PYTHON"))}
        env.update(LANG="C", LC_ALL="C")
        r, _ = hook(json.dumps({"prompt": notice()}, ensure_ascii=False), env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.isascii())
        self.assertIn("发布 0.3.0", json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_it_is_quick(self):
        """It runs on every prompt of every session where the plugin is enabled: about 13 ms on 2026-10-26."""
        times = [hook(json.dumps({"prompt": "Please refactor the parser " * 200}))[1] for _ in range(7)]
        self.assertLess(statistics.median(times), 300, times)      # generous for slow CI machines


class Config(unittest.TestCase):
    def test_the_plugin_registers_it_for_every_prompt(self):
        """A plugin hook, not one in the skill's frontmatter: Claude Code 2.1.299 never ran a forked skill's own
        UserPromptSubmit hook (2026-10-26). The command cannot fail a prompt: errors go nowhere and it exits 0."""
        with open(os.path.join(ROOT, "hooks", "hooks.json"), encoding="utf-8") as f:
            conf = json.load(f)
        self.assertEqual(list(conf["hooks"]), ["UserPromptSubmit"])
        (h,) = [h for group in conf["hooks"]["UserPromptSubmit"] for h in group["hooks"]]
        self.assertEqual(h["type"], "command")
        self.assertIn('python3 -I -S "${CLAUDE_PLUGIN_ROOT}/scripts/notice_hook.py"', h["command"])
        self.assertTrue(h["command"].endswith("2>/dev/null || true"))
        self.assertLessEqual(h["timeout"], 10)
        with open(os.path.join(ROOT, "skills", "treesight", "SKILL.md"), encoding="utf-8") as f:
            skill = f.read()
        self.assertNotIn("hooks:", skill.split("---", 2)[1])
        self.assertIn("`%s`" % treesight.REPORT_HEAD, skill)       # the line the hook looks for is the one the skill writes
        self.assertEqual(notice_hook.HEAD, treesight.REPORT_HEAD)


if __name__ == "__main__":
    unittest.main()

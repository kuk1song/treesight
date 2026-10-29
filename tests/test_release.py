"""dev/check_release.py, the check that plugin.json's version, its CHANGELOG section and a release tag agree.
Run: python3 -m unittest discover -s tests"""
import contextlib
import copy
import io
import json
import os
import sys
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "dev"))

import check_release  # noqa: E402


class Release(unittest.TestCase):
    def test_the_repository_agrees_with_itself(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check_release.main([]), 0)

    def test_a_tag_must_name_the_version(self):
        with self.assertRaises(SystemExit) as e:
            check_release.main(["--tag", "v0.0.0"])
        self.assertIn("does not match", str(e.exception))

    def test_sections(self):
        text = "# Changelog\n\n## Unreleased\n\n- next\n\n## 1.2.0 (2026-01-02)\n\n- this\n\n## 1.1.0 (2025-12-01)\n\n- that\n"
        self.assertEqual(check_release.sections(text), [("Unreleased", "- next"), ("1.2.0", "- this"), ("1.1.0", "- that")])
        with self.assertRaises(SystemExit):
            check_release.sections("## 1.2 (2026-01-02)\n")

    def test_the_marketplace_installs_a_release(self):
        """With "./" the marketplace gave new installs main under the last version number; the entry now names a
        release's tag and its commit, and repeats plugin.json's fields, which Claude Code shows before install only
        from the entry when the source is not a folder of the marketplace."""
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            plugin = json.load(f)
        with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"), encoding="utf-8") as f:
            market = json.load(f)
        src = market["plugins"][0]["source"]
        good = lambda tag: src["sha"]
        self.assertEqual(check_release.check_pin(market, plugin, ["0.3.0", src["ref"][1:]], good), src["ref"])   # a release waiting for its tag

        def fails(change, released=(src["ref"][1:],), commit=good):
            m = copy.deepcopy(market)
            change(m["plugins"][0])
            with self.assertRaises(SystemExit):
                check_release.check_pin(m, plugin, list(released), commit)

        fails(lambda e: e.__setitem__("source", "./"))
        fails(lambda e: e["source"].__setitem__("repo", "someone/treesight"))
        fails(lambda e: e["source"].__setitem__("ref", "main"))
        fails(lambda e: None, released=("0.4.0", "0.3.0", src["ref"][1:]))     # two releases behind
        fails(lambda e: e["source"].__setitem__("sha", src["sha"][:12]))
        fails(lambda e: e.__setitem__("license", "Apache-2.0"))
        fails(lambda e: e.__setitem__("version", plugin["version"]))
        fails(lambda e: None, commit=lambda tag: "0" * 40)                      # sha is not the tag's commit
        fails(lambda e: None, commit=lambda tag: None)                          # the tag does not exist


if __name__ == "__main__":
    unittest.main()

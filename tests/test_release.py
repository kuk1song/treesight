"""dev/check_release.py, the check that plugin.json's version, its CHANGELOG section and a release tag agree.
Run: python3 -m unittest discover -s tests"""
import contextlib
import io
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


if __name__ == "__main__":
    unittest.main()

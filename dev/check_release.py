#!/usr/bin/env python3
"""Check that the version in .claude-plugin/plugin.json has its own CHANGELOG.md section, and with --tag that
the tag names that version. CI runs it on every change; the release workflow runs it with the pushed tag and
--notes to write that section as the release notes.

Usage: python3 dev/check_release.py [--tag vX.Y.Z] [--notes FILE]
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
HEADING = re.compile(r"^## (Unreleased|(\d+\.\d+\.\d+) \((\d{4}-\d{2}-\d{2})\))$")


def sections(text):
    """CHANGELOG sections as [(name, body)], in file order; name is "Unreleased" or a version."""
    out, name, body = [], None, []
    for line in text.splitlines():
        if line.startswith("## "):
            m = HEADING.match(line)
            if not m:
                raise SystemExit("CHANGELOG.md: %r is neither '## Unreleased' nor '## X.Y.Z (YYYY-MM-DD)'" % line)
            if name:
                out.append((name, "\n".join(body).strip()))
            name, body = m.group(2) or m.group(1), []
        elif name:
            body.append(line)
    if name:
        out.append((name, "\n".join(body).strip()))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tag")
    ap.add_argument("--notes")
    a = ap.parse_args(argv)
    with open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
        version = json.load(f)["version"]
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        found = sections(f.read())
    names = [n for n, _ in found]
    if version not in names:
        raise SystemExit("CHANGELOG.md has no '## %s (YYYY-MM-DD)' section for plugin.json's version" % version)
    released = [n for n in names if n != "Unreleased"]
    if released[0] != version:
        raise SystemExit("plugin.json says %s but the newest CHANGELOG release is %s" % (version, released[0]))
    if a.tag and a.tag != "v" + version:
        raise SystemExit("tag %s does not match plugin.json's version %s" % (a.tag, version))
    body = dict(found)[version]
    if not body:
        raise SystemExit("the CHANGELOG section for %s is empty" % version)
    if a.notes:
        with open(a.notes, "w", encoding="utf-8") as f:
            f.write(body + "\n")
    print("ok: plugin.json %s, CHANGELOG section of %d characters%s" % (version, len(body), ", tag " + a.tag if a.tag else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

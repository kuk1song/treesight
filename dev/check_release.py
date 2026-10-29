#!/usr/bin/env python3
"""Check that the version in .claude-plugin/plugin.json has its own CHANGELOG.md section, and with --tag that
the tag names that version; and that the marketplace entry installs a release: a github source whose ref is a
released version's tag and whose sha is a full commit, with plugin.json's fields, which Claude Code shows before
install only from the entry. With --tags, sha must be that tag's commit in this repository. CI runs it with --tags
on every change; the release workflow runs it with the pushed tag and --notes to write that section as the
release notes.

Usage: python3 dev/check_release.py [--tag vX.Y.Z] [--notes FILE] [--tags]
"""
import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
HEADING = re.compile(r"^## (Unreleased|(\d+\.\d+\.\d+) \((\d{4}-\d{2}-\d{2})\))$")
SHOWN = ("description", "author", "homepage", "repository", "license", "keywords")   # what the entry shows for plugin.json


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


def tag_commit(tag):
    """The commit a tag of this repository points at, or None when there is no such tag (or no git)."""
    try:
        r = subprocess.run(["git", "-C", ROOT, "rev-parse", "--verify", "--quiet", "refs/tags/%s^{commit}" % tag],
                           capture_output=True, text=True)
    except OSError:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def check_pin(market, plugin, released, commit=None):
    """The marketplace entry installs a release rather than main: a github source of this repository whose ref is
    the tag of the newest release, or of the one before while a release waits for its tag, and whose sha is a full
    commit (Claude Code checks out sha). commit(tag), when given, must find that tag and give sha. Returns the ref."""
    entries = [e for e in market.get("plugins", []) if e.get("name") == plugin["name"]]
    if len(entries) != 1:
        raise SystemExit("marketplace.json needs exactly one entry named %r" % plugin["name"])
    e, repo = entries[0], re.sub(r"^https://github\.com/", "", plugin["repository"])
    src = e.get("source")
    if not isinstance(src, dict) or src.get("source") != "github" or src.get("repo") != repo:
        raise SystemExit("marketplace.json: the entry's source must be {\"source\": \"github\", \"repo\": %r, ...}" % repo)
    ref, sha = src.get("ref", ""), src.get("sha", "")
    if not ref.startswith("v") or ref[1:] not in released[:2]:
        raise SystemExit("marketplace.json: ref %r is not the tag of the newest release (%s)" % (ref, ", ".join("v" + v for v in released[:2])))
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise SystemExit("marketplace.json: sha must be a full 40-character lowercase commit")
    for k in SHOWN:
        if e.get(k) != plugin.get(k):
            raise SystemExit("marketplace.json: the entry's %s differs from plugin.json's" % k)
    if "version" in e:
        raise SystemExit("marketplace.json: leave version to plugin.json")
    if commit:
        got = commit(ref)
        if got != sha:
            raise SystemExit("marketplace.json: sha %s is not the commit of tag %s (%s)" % (sha, ref, got or "no such tag here"))
    return ref


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tag")
    ap.add_argument("--notes")
    ap.add_argument("--tags", action="store_true", help="also check that the marketplace's sha is its tag's commit here")
    a = ap.parse_args(argv)
    with open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
        plugin = json.load(f)
    with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"), encoding="utf-8") as f:
        market = json.load(f)
    version = plugin["version"]
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
    ref = check_pin(market, plugin, released, tag_commit if a.tags else None)
    body = dict(found)[version]
    if not body:
        raise SystemExit("the CHANGELOG section for %s is empty" % version)
    if a.notes:
        with open(a.notes, "w", encoding="utf-8") as f:
            f.write(body + "\n")
    print("ok: plugin.json %s, CHANGELOG section of %d characters%s; the marketplace installs %s%s"
          % (version, len(body), ", tag " + a.tag if a.tag else "", ref, " (its commit checked)" if a.tags else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

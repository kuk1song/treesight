# Contributing

Bug reports and pull requests are welcome. For a security problem, follow [SECURITY.md](SECURITY.md) instead of opening an issue.

## Privacy first

treesight reads people's own Claude Code sessions, so nothing from a real session may enter this repository: no session text, local paths, emails, addresses or keys, in code, tests, fixtures, docs or issues. Examples and tests use made-up projects in `fixtures/`: tidepool for the tests and the measurements in `docs/design.md`, and recipe-box, in English and Chinese, for the README demo. `dev/make_fixtures.py` rebuilds their transcripts, and CI checks that they and `docs/demo.html` are current.

## Checks

Python 3.9 or later and the standard library only. Eight tests of the page's script need `node`, one cross-check needs the `jsonschema` package, and two drive the page in a headless Chromium (`dev/check_page.py` loads every view, `dev/check_live.mjs` checks that an open page updates itself and that nodes, links, branches, the line while drawing and growth work with a mouse; Playwright's chrome-headless-shell, or `google-chrome` on Linux, and Node 22 or later for the second); they are skipped when those are missing.

```bash
python3 -m unittest discover -s tests     # tests
python3 dev/make_sample.py                # rebuild docs/demo.html (the recipe-box demo) from fixtures/
node dev/record_demo.mjs en|zh            # record a README video (needs Node 22 or later, ffmpeg and chrome-headless-shell)
python3 dev/palcheck.py                   # colour contrast of the page
python3 dev/check_page.py                 # every view of the page in a headless browser, no script errors
node dev/check_live.mjs <chromium>        # an open page follows a correction and a run without a new tab; nodes, links, growth (Node 22 or later)
python3 dev/check_release.py --tags       # plugin.json's version has its CHANGELOG section; the marketplace installs a release's tag and commit
claude plugin validate --strict .         # in a clean checkout
```

To try a change in Claude Code, start it with `claude --plugin-dir <a clean checkout>` and run `/treesight:treesight` in a session that has a few prompts. The design and its reasons are in [docs/design.md](docs/design.md).

## Pull requests

- Branch from `main` and open a pull request; `main` only changes through pull requests whose CI passes.
- Keep `README.md` and `README.zh-CN.md` saying the same things.
- Pull requests are squash-merged: the pull request's title and description become the commit on `main` (a repository setting since 2026-10-31).

## Releases

Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Before 1.0, a release with a new feature, or with any change that an earlier version cannot read or call the same way (the ledger's or a schema's format, the command's arguments, the script's JSON), raises the minor version (0.2.0 to 0.3.0); a release with fixes only, including changes to how existing parts look or are worded, raises the patch version (0.2.0 to 0.2.1). Each pull request adds its user-visible changes under `## Unreleased` in `CHANGELOG.md`, in the groups listed there, with its number; anything an update asks of users goes under "Before you update".

1. In a pull request, set the new version in `.claude-plugin/plugin.json` and rename `## Unreleased` in `CHANGELOG.md` to `## X.Y.Z (YYYY-MM-DD)`. Before merging it, run `claude --plugin-dir <a clean checkout of the branch>` in your own configuration, draw a small session with `/treesight:treesight`, and check the page and the two report lines.
2. After it is merged, tag the commit the squash merge made on `main` (the branch's own commits never reach `main`) and push the tag: `git switch main && git pull --ff-only && git tag -a vX.Y.Z -m "treesight X.Y.Z" && git push origin vX.Y.Z`.
3. The release workflow checks that the tag points at a commit on `main`, runs the tests, checks that the tag, `plugin.json` and `CHANGELOG.md` agree, then publishes the GitHub release with that CHANGELOG section as its notes. Releases are immutable once published (a repository setting, on since 2026-10-27): the tag cannot be moved, and only the title and notes can be edited. A ruleset keeps every `v*` tag from being deleted or moved even before that (since 2026-10-31), so check the commit before pushing a tag.
4. In a second pull request, move the marketplace entry's `ref` and `sha` in `.claude-plugin/marketplace.json` to the new tag and its commit (`git rev-parse vX.Y.Z^{commit}`); CI's `dev/check_release.py --tags` checks that they agree. Before merging it, install it as users will get it: in a throwaway configuration (`export CLAUDE_CONFIG_DIR="$(mktemp -d)"`), run `claude plugin marketplace add kuk1song/treesight@<the branch>` and `claude plugin install treesight@treesight`, and compare the installed copy under `$CLAUDE_CONFIG_DIR/plugins/cache/` with `git archive vX.Y.Z`. Once it is merged, users get the release as the README's Install section says.

The marketplace entry names the latest release's tag and commit, so new installs and updates get released versions only; a change merged to `main` reaches users with the next release.

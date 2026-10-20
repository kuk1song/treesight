# Contributing

Bug reports and pull requests are welcome. For a security problem, follow [SECURITY.md](SECURITY.md) instead of opening an issue.

## Privacy first

treesight reads people's own Claude Code sessions, so nothing from a real session may enter this repository: no session text, local paths, emails, addresses or keys, in code, tests, fixtures, docs or issues. Examples and tests use made-up projects in `fixtures/`: tidepool for the tests and the measurements in `docs/design.md`, and recipe-box, in English and Chinese, for the README demo. `dev/make_fixtures.py` rebuilds their transcripts, and CI checks that they and `docs/demo.html` are current.

## Checks

Python 3.9 or later and the standard library only. Four tests of the page's script need `node`, and one cross-check needs the `jsonschema` package; they are skipped when those are missing.

```bash
python3 -m unittest discover -s tests     # tests
python3 dev/make_sample.py                # rebuild docs/demo.html (the recipe-box demo) from fixtures/
node dev/record_demo.mjs en|zh            # record a README video (needs Node 22 or later, ffmpeg and chrome-headless-shell)
python3 dev/palcheck.py                   # colour contrast of the page
python3 dev/check_release.py              # plugin.json's version has its CHANGELOG section
claude plugin validate --strict .         # in a clean checkout
```

To try a change in Claude Code, start it with `claude --plugin-dir <a clean checkout>` and run `/treesight:treesight` in a session that has a few prompts. The design and its reasons are in [docs/design.md](docs/design.md).

## Pull requests

- Branch from `main` and open a pull request; `main` only changes through pull requests whose CI passes.
- Note user-visible changes under `## Unreleased` in `CHANGELOG.md`. Keep `README.md` and `README.zh-CN.md` saying the same things.
- Pull requests are squash-merged, so the title becomes the commit message.

## Releases

1. In a pull request, set the new version in `.claude-plugin/plugin.json` and rename `## Unreleased` in `CHANGELOG.md` to `## X.Y.Z (YYYY-MM-DD)`.
2. After it is merged, tag that commit and push the tag: `git tag -a vX.Y.Z -m "treesight X.Y.Z" && git push origin vX.Y.Z`.
3. The release workflow checks that the tag, `plugin.json` and `CHANGELOG.md` agree, then publishes the GitHub release with that CHANGELOG section as its notes. Users get it with `claude plugin update treesight@treesight`.

The marketplace installs straight from `main`, so a merged change to what ships (`scripts/`, `skills/`, `templates/`, `schema/`, `.claude-plugin/`) reaches new installs at once, still under the last version number, while existing installs only update on a new version. Release soon after merging such a change.

# Changelog

## Unreleased

- Page: the Chinese interface puts a space between 在等 and a name in Latin letters (在等 Alex).
- README: a shorter tagline about recalling a session, not tied to one agent, written separately in Chinese; where treesight runs, in two sentences, with the full list and its sources in `docs/design.md`.
- Page: in a window narrower than 1020 pixels, the way back to the whole project is a button with an arrow on its own line, instead of a plain button in the legend's row that looked like one of its items.
- README: a centered header; a logo that grows once, pings its open ring twice and is still within about 4 seconds (its resting state is the finished tree, so it shows whole where animation does not run); Install first, with the one-step command in Claude Code, the command a coding agent can run in a terminal, and how to update; details and measurements left to `docs/design.md` instead of repeated; the comparison table folded.

## 0.1.1 (2026-10-20)

- The page's interface language is the first of the browser's preferred languages that the page has (Chinese or English), instead of only the first preferred language.
- The design document (`docs/design.md`) is now in English.
- README: a logo, a five-second animation of the sample page in place of the two screenshots, a three-step quick start, a Using it section and where to get help. Images use Markdown syntax.
- Contributing guide, bug report form and pull request template. Releases are published by a workflow that first checks that the tag, `plugin.json` and `CHANGELOG.md` agree; Dependabot keeps the pinned GitHub Actions current.

## 0.1.0 (2026-10-20)

First public release.

- `/treesight:treesight` draws a Claude Code session as a tree of what got done and what was found, with setbacks shown as scars that open into a three-row story, and lists what is still open across the project: yours to do or waiting, who it waits on and for how long, overdue, blocked by another item.
- Extraction runs in a forked subagent with the user's own Claude Code. It reads the session's texts whole, in passes of up to 150,000 characters for long sessions, and the skill pre-approves only running treesight's own script and writing under `~/.cache/treesight`. The skill sets xhigh effort, so results do not depend on the session's effort level. Every node and open item carries a quote that a script checks against the session before saving.
- Append-only ledger in `~/.local/share/treesight/`: later runs read only new messages, treesight's own command and the turn spent on its report are not counted, closes need a quote from no earlier than the item, unsure ones wait for the user, an older session drawn after newer ones is checked against what they recorded, and the user's own corrections (`close`, `reopen`, `hide`, `set`) are checked and always win. The ledger keeps each session's title and times, so a session stays on the page after Claude Code deletes its transcript. Writes are locked, pages are written under the same lock so an older state never replaces a newer page, and files are readable only by the user.
- Static page with no network requests, a Content Security Policy, English and Chinese interface, project and session views with browser history. It opens on the session being drawn, lists every run in progress, and says when they seem to have stopped. On macOS it is opened with `open -a` and the default browser; `$BROWSER` is honoured.
- Transcript reading, secret scrubbing and IPv4 and email masking in one adapter; data formats as JSON Schema; tests with the Python standard library only.

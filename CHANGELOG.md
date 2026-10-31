# Changelog

From 0.2.0 on, changes are grouped as in [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), with "Before you update" first and "Development" last, and versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) as `CONTRIBUTING.md` describes. Numbers in parentheses are pull requests.

## 0.2.2 (2026-10-31)

### Security

- Keys and tokens written right after Chinese or Japanese text are masked: `密钥是sk-…` was kept whole in the digest, the ledger and the page, because Python counts those characters as part of a word. PGP private key blocks and the private part of PuTTY key files are masked too. (#28)

### Fixed

- Masking an address right after Chinese text no longer takes the Chinese with it (发邮件到 was lost). (#28)
- A ledger write that fails part way, on a full disk say, is cut back off, so a run is never kept with only some of its nodes. (#28)
- Odd transcript records (a time that is null, a number or without its zone; a message that is not an object; text that is not a string; a lone surrogate; a session id that is a path) are read instead of stopping the whole project with a traceback, and anything else unexpected is reported as an error. (#28)
- `/treesight:treesight --no-open` or `--restart` on its own was refused: the skill now passes the words with an equals sign. (#28)
- Page, with the keyboard: the drawer takes the focus when it opens and gives it back when Esc or × closes it; the crown's button, "Show all" and × show where the focus is; "Show all" keeps the focus. The drawer no longer slides when motion is reduced, and from 641 to 660 px hover cards no longer widen the page. (#28)
- Masking many BEGIN lines of a private key without an END took seconds; it is linear now. (#28)
- README: a run's report has a third line when something needs you. (#28)

### Development

- `dev/check_page.py` fails when the page's script does not run (a wrong script hash left a blank page that passed); `dev/check_live.mjs` drives the drawer from the keyboard and checks the width at 650 px; CI checkouts keep no token. (#28)

## 0.2.1 (2026-10-29)

### Changed

- The marketplace installs the latest release instead of `main`: its entry names the release's tag and commit, so a change merged after a release reaches new installs with the next release, not at once. (#24)
- Page: the line under "Draw the tree" and "Open the session" no longer shows before a click. Hovering either link, or reaching it with the keyboard, shows one tip under both: the browser asks first, which button to click, then Enter in the terminal; Esc hides it. After a click the line says it again, with the command to copy. (#25)
- README: to update, run `claude plugin marketplace update treesight` before `claude plugin update treesight@treesight`; the second alone may not fetch the marketplace again and then reports the version you have as the latest. (#25)

### Fixed

- The page said to choose "Open or Allow" in the browser's prompt, but the buttons of Chrome and Firefox start with Open, and in Chrome Allow is only on the "Always allow" checkbox the page does not suggest; it now names Allow in Safari, whose button says it, and Open elsewhere. (#25)

### Development

- The tests no longer open the made-up tidepool page in the developer's browser; one of them built the page with `--open`. (#25)
- `dev/check_live.mjs` checks the tip on hover, with Esc and at a phone's width, and a browser request left without an answer fails it after 10 s instead of hanging until the test's timeout. (#25)

## 0.2.0 (2026-10-29)

### Before you update

- Do not go back to 0.1.3 or earlier afterwards: this version's ledger holds fields those versions refuse when they draw the page (a `twig` on a node's quote, twigs of up to 16 units) or ignore (overviews). (#17, #18)
- The plugin now adds a hook that looks at each prompt you send, in memory, for treesight's own completion notice; it keeps nothing, sends nothing and lets every other prompt through. (#19)
- Short excerpts of the project's other sessions now reach the model too, so it can write their overviews. (#18)

### Added

- Session overviews (会话概况): one sentence per session, marked AI, written from the whole session for the one drawn and from a short excerpt for up to 30 others a run; an overview from a session's own run is never replaced by one from an excerpt. (#18, #19)
- Links into Claude Code: a session without a tree, when clicked, shows its overview and "Draw the tree" and "Open the session", which open Claude Code in a new terminal with the command typed in (`claude-cli://` deep links; nothing runs until Enter), and a command to copy if nothing opens. A line under them says first that the browser asks before it opens Claude Code and which button to choose. A run started this way updates the open page instead of opening another tab. (#18, #19, #23)
- One page per project, kept current: the browser opens it once per conversation (again after three hours without an update there), and later runs and corrections update the open page through a one-line stamp file next to it, instead of a new tab or a reload every 20 seconds. (#17)
- While a session is drawn, a pill at the top says "Drawing a tree", which session, and about how many minutes, beside a small growing tree with a pause button; the project tree grows on such a page too. (#18, #19)
- When a run is done, your conversation shows two short lines starting with `🌳 treesight:`: what changed and the page's link, plus a line only when something needs you. The script writes them in the language of the session's prompts, and the plugin's hook asks the main conversation to show them as they are instead of reviewing the run on its own. (#19)
- A small "quote" mark after a node's sentence or twig opens who wrote the quote, when, and its words; it replaces the "Show source" box, and open items in the drawer work the same way. (#17, #18)
- Hovering a session with a tree shows its overview, marked AI, and its numbers of nodes and open items. After a run started from the page, the white dot stays on the conversation you came from. (#18, #19)
- `/treesight:treesight <session> --restart` starts again after a run was stopped, instead of waiting until 20 minutes past its estimate. (#17)
- Open items whose due date is still ahead are listed under "With a due date", soonest first, with the days left. (#17)

### Changed

- Sessions and items are found by words in any order, and when several match, the message lists titles or labels; `set <item> blocked_by=<words>` finds the other item by its words. (#17)
- Page: sessions without a tree are rings, with a legend once some session has a tree; before any tree exists there is no open-items line; the project's name shows with its path on hover. (#17, #18)
- Page: an expanded node is one panel, flush left: its sentence or story, then its twigs as a list. (#18)
- Page: ranked open items list the newer session's first. Chinese the model wrote gets full-width punctuation where it touches Chinese. English wording: "Needs your “…” first", "Below, in the order raised", "No tree yet". Chinese: 尚未生成树 in the legend, 已生成树的 n 个会话 in the drawer. (#17, #19, #22)
- What a run was unsure about stays in the ledger and is no longer shown; a run read in two passes counts as one run under the session's title. (#17, #19)
- Sessions run with `claude -p` or the Agent SDK are listed only once drawn; the footer says how many. (#18)
- Extraction: twigs may have 16 units instead of 10, as phrases that make sense on their own a month later. The guide asks for one node where a thread ended up, leaves out Claude's own queued work and offers you did not take up, and keeps usage-limit waits and time away out of stuck time. (#17, #18)
- The digest is shown to the model in parts of at most 24,000 bytes rather than 20,000 characters, so Claude Code shows each part inline. (#17)
- The English report reads "the tree of “…” is ready (3 new nodes, 2 new open items)" and names items and messages in its extra lines. (#22)
- README: the links' limitation says what the browser asks and where the links were tried; a run with nothing new takes 18 to 44 seconds in testing. (#23)
- README: a 35-second video of a project's first run in each language, from the command to the report, zoomed where the action is, with an end card that has the install command; coding agent in Chinese; no line on not being affiliated with Anthropic. (#20, #22)

### Fixed

- Every branch ends at its node's dot; the tip used to stop 7 to 20 px above it. (#19)
- A compaction summary whose headings are in Markdown (`1. **Pending Tasks**`) keeps its Pending Tasks when shortened; it was cut from its end. One whose headings are not recognized keeps its start and its end. (#21)
- A name with token, password or secret in it no longer takes the Chinese text after it for its value (`token: 我已经…` lost the whole sentence). (#21)
- A ledger whose last line a crash left unfinished no longer blocks the project; the line is left out and removed on the next write. (#21)
- Errors instead of tracebacks for a transcript without messages, a transcript line that is JSON but not an object, an extraction whose session is not a string, and wrong arguments. (#17, #21)
- Output is UTF-8 whatever the console's code page, so on Windows a run's report is no longer lost; the browser is asked with the page's own `file://` URL; `apply` looks for the digest first, so a run another one finished stops. Long file names wrap in hover cards and expanded nodes. (#17, #21)

### Security

- Secrets are masked before any text is cut, so a private key in long pasted text or across a compaction summary's limit no longer leaves its first lines in the digest, the ledger or the page. (#17)
- More secret formats are masked: Groq, SendGrid, Telegram, Discord, Slack app and Shopify tokens, Google OAuth client secrets, Stripe webhook secrets, Slack and Discord webhook URLs, Azure storage keys, `--password <value>` and the like, names ending in `_KEY` with a key-like value, passphrases and all-digit passwords; the patterns take linear time on long text without spaces. (#17)
- What the model wrote is scrubbed before the ledger keeps it, as the page already did. (#21)

### Development

- `dev/check_page.py` loads every view of the page in a headless browser, and `dev/check_live.mjs` drives an open page through corrections, runs, clicks and growth; the tests run both when a browser is found. (#17, #19)
- `dev/make_sample.py --first-run DIR` writes the pages and report of a first run, which `dev/record_demo.mjs` records; the recorder's terminal wraps lines at spaces, as Claude Code does. (#20, #22)
- The bug form asks for treesight's version and how it was installed; `SECURITY.md` says which versions get fixes; `CONTRIBUTING.md` has the versioning rule and a release checklist. (#22)

## 0.1.3 (2026-10-20)

- Page: the Chinese interface uses full-width Chinese punctuation (：，；？（）), as Chinese typography guides ask.
- Secret scrubbing also removes Stripe secret and restricted keys, GitLab, npm and Hugging Face tokens, Google OAuth access tokens and HTTP basic credentials.
- A run's digest and extraction are deleted when the run ends, also when it fails, instead of staying until the next run.
- The page still builds when a session title or summary holds addresses or secrets near the length limit (they are now masked before being cut), and when an old ledger has items raised on a date without a time.
- Page: long file names and paths wrap instead of running off a narrow screen; English says "1 day"; the Chinese interface ends its sentences with 。, says 已过 n 天 for put-off items as well as waits, and spaces Latin names that start with an accented letter.
- The command line also answers file system errors with `{"ok": false, "error": …}`, which the skill reads, and `set` explains a field without `=` or a rank that is not a whole number.
- treesight restricts only the folders it creates; a folder that already exists keeps its permissions.
- README: the opening is a question, then what treesight does and that it runs as a plugin inside your AI; the logo waits about 0.95 s before it grows, so the growth is not over before GitHub shows the page; the top note became one line under License and "dark theme only" a limitation; the caption under the video is gone; a run with nothing new is said to cost one short model turn; the Chinese README uses full-width punctuation and says 没做完.
- Demo: both demo projects live in /home/kuki/recipe-box; the Chinese one reads more naturally (为菜谱添加照片上传功能, 旋转方向单独存储, 删菜谱也删照片); the video cover shows the logo, the name and the three steps; both videos re-recorded.
- CI checks that `docs/demo.html` and `fixtures/` match the scripts that build them and pins the Claude Code and jsonschema versions it tests with; the release workflow runs the tests and checks that the tag is on `main` before publishing.

## 0.1.2 (2026-10-20)

- Page: in a window narrower than 1020 pixels, the way back to the whole project is a button with an arrow on its own line, instead of a plain button in the legend's row that looked like one of its items.
- Page: the Chinese interface puts a space between 在等 and a name in Latin letters (在等 Alex).
- Sample pages built with a fixed time count days to that date, so their numbers do not grow over time.
- README: a centered header and a logo that comes to rest within about 4 seconds; a shorter tagline about recalling an AI session, written separately in Chinese; Install first, with the one-step command, the command a coding agent can run in a terminal, and how to update; where treesight runs, in two sentences; details and measurements left to `docs/design.md` instead of repeated.
- README demo: a 21-second video with step captions, in English and in Chinese, of a made-up recipe website instead of the tide-table GIF; readers can pause and scrub it. `dev/record_demo.mjs` records it from the sample page.
- The plugin's description follows the new tagline.

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

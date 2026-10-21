# Changelog

## Unreleased

- Secrets are masked before any text is cut, so a private key in long pasted text or across a compaction summary's limit no longer leaves its first lines in the digest, the ledger or the page. Scrubbing also covers Groq, SendGrid, Telegram, Discord, Slack app and Shopify tokens, Google OAuth client secrets, Stripe webhook secrets, Slack and Discord webhook URLs, Azure storage account keys, `--password <value>` and the like, names ending in `_KEY` with a key-like value, passphrases, and all-digit passwords, and it takes linear time on long text without spaces, where the email, URL and token-name patterns could take seconds.
- Page: an open item whose due date is still ahead is listed under "With a due date", soonest first, with its date and the days left; before, it fell under "No time set" and its date showed only once it had passed.
- Sessions and items are found by words in any order (titles as written, so words that are masked on the page still match), and when several match, the message lists sessions' titles beside their ids, and items' labels instead of their ids. `set <item> blocked_by=<words>` finds the other item by its words. A number of 4 to 7 hex characters, such as 8080, only matches sessions of the current project.
- `/treesight:treesight <session> --restart` starts again after a run was stopped; until now a stopped run blocked the session for 20 minutes past its estimate. A run that was in fact still going cannot record the same entries twice.
- The digest is shown to the model in parts of at most 24,000 bytes rather than 20,000 characters: Claude Code saved a mostly Chinese part of 20,000 characters (about 35,000 bytes) to a file instead of showing it, so the model needed an extra step to read it.
- Page: before any session has a tree, the project page shows no open-items line; it used to say "Nothing left open" and "From 0 sessions with a tree". Once there is a tree, the line under the count reads "Only the N sessions with a tree, of M", or "From all M sessions".
- Page: a session without a tree says so on hover and, when clicked, shows its summary and the command that draws it, with a copy button. Its summary skips a first prompt that is output pasted from another session.
- The report in the conversation is three lines: a fixed first line, what changed in numbers only, and the page's link. What the run was unsure about is on the page, under the session's title, and a run read in two passes counts as one run there, so the counts under the title match the report (before, they were the last pass's only).
- One page per project, kept current: the browser opens it on the first run of a conversation (and again after three hours without an update there), and later runs and corrections in that conversation update the open page instead of opening another tab. The page checks a one-line stamp file next to it and reloads only when there is a newer build, instead of reloading every 20 seconds while a session is drawn; a page built on your machine adds `'strict-dynamic'` to its Content Security Policy so its own script can load that stamp.
- Page: while a session is being drawn, a light runs round the line that says so (a click pauses it; it stays still with reduced motion and once the run seems to have stopped). The line reads "Drawing the tree of session “…” · about N min · updates itself when done".
- Page: the quotes behind a node follow its twigs as who said them and when, and open with a click, instead of a "Show source" box; quotes tied to no twig are listed under "Sources", twigs show under a story too, and open items in the drawer show their sources when clicked. Where there is hover, an expanded node no longer repeats the sentence its hover card shows; notes such as "merged" stay. Extraction may tie each quote to the twig it shows; the ledger stores quotes from the node's own message first.
- Page: ranked open items list the newer session's first, so two first-ranked items from different sessions no longer sit side by side; waiting items keep their rank.
- Extraction guide: one node for where a thread ended up; a node's message is where its outcome shows; Claude's own queued work is not something you wait on; an offer you did not take up is not an open item unless work waits on it; an undecided earlier item that decides whether a new one applies is set as its blocker; stuck time leaves out usage-limit waits and time away; "be conservative" removed.
- `dev/check_page.py` loads every view of the page in a headless browser and fails on any script error, and `dev/check_live.mjs` checks that an open page follows a correction and a run without a new tab; the tests run both when a browser is found.
- The ledger can now hold a `twig` on a node's quote, which 0.1.3 and earlier refuse when they draw the page: after updating, do not go back to an earlier version.
- Wrong arguments to the command line answer `{"ok": false, …}` like other errors. Hover cards and expanded nodes wrap long file names too.
- Documents: a run with nothing new takes a few short model requests (about 20 s), not one; CONTRIBUTING counts six tests that need node and lists every step of the release workflow. Both README videos are re-recorded: a node's quotes follow its twigs.

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

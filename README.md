<div align="center">

![treesight logo: a small tree with two done dots and one open ring](docs/logo.svg)

# treesight

**Recall what each AI session did, and what it left open.**

**English** · [中文](README.zh-CN.md)

</div>

Do you find it hard, after a while, to recall how a session went and its details? Give treesight a try :)

treesight reads the whole session and draws it as a tree: what got done, what was found, where it got stuck, and what is still open. It runs as a plugin inside your AI: no server, no account, no extra API key, and the page makes no network requests.

https://github.com/user-attachments/assets/3e5efb9a-1699-41e0-9e67-a4312527d83b

## Install

In Claude Code 2.1.275 or later:

```
/plugin install treesight --marketplace kuk1song/treesight
```

Then choose where to install it. On an older version, run `/plugin marketplace add kuk1song/treesight` and then `/plugin install treesight@treesight`.

**Letting your coding agent set it up?** Ask it to run this in a terminal (Claude Code 2.1.292 or later), then run `/reload-plugins` yourself or start a new session:

```
claude plugin install treesight --marketplace kuk1song/treesight
```

It works in Claude Code on your own computer: tested in the terminal, while the desktop app's Code tab and the IDE extensions should work but are untested. It does not run in cloud sessions, Cowork, claude.ai chat or other coding agents ([details](docs/design.md#5-delivery)).

treesight also needs `python3` 3.9 or later (Apple's, from the Command Line Tools, works) on macOS or Linux; Windows is untested. Tested with Claude Code 2.1.299. Updates are off by default for a marketplace like this one: turn them on in `/plugin`, or run `claude plugin marketplace update treesight` and `claude plugin update treesight@treesight`, then `/reload-plugins` or a new session.

## Use

Open the session you want to see (for example with `claude --resume`) and run:

```
/treesight:treesight
```

Within seconds treesight asks your browser to open the page, and the session's tree appears there when the background run is done, a few minutes for most sessions. Keep working meanwhile. When it is done, two short lines in your conversation say what changed, with the page's link, and a third when something needs you. Later runs and corrections in the same conversation update that page instead of opening another tab.

- **Another session of this project:** add its id or words from its title, in any order, as in `/treesight:treesight 0a182a7b` or `/treesight:treesight release`. The project page lists the project's sessions: click one without a tree for its session overview, and for links that open Claude Code with the command to draw it, or to resume it, typed in.
- **Run it again** to read only what is new. A run started while another is still going runs in the foreground, so your conversation waits for it. If you stopped a run, add `--restart` to start that session again.
- **Correct the page:** `/treesight:treesight close <words from an item's label>`, or `reopen`, `hide`, or `set <item> when=after the trip` (fields: label, line, kind, due, when, who, rank, score, blocked_by). Your corrections always win.

## How it works

1. **Read:** a script reads the transcript in `~/.claude/projects` without any model, removes common secret formats, and masks IPv4 addresses and emails.
2. **Extract:** a subagent in the background picks out the nodes and open items with your own model and account, leaving your conversation as it is. Each must quote the session word for word. It also writes a one-sentence overview of each of the project's other sessions that needs one, from a short excerpt of it.
3. **Check and save:** a script checks every quote against the message it cites, then appends the result to a local ledger. Later runs read only what is new, and when the model is not sure an item is finished, it waits for you to confirm.
4. **Draw:** a script builds one static page per project. No model is involved.

The skill pre-approves only two things: running its own script, and writing its result under `~/.cache/treesight`. Anything else follows your usual permission settings. What is shortened, what is checked and where each file lives are in [docs/design.md](docs/design.md).

## Privacy

- The page makes no network requests. Its Content Security Policy runs no script but its own (allowed by hash) and the files that script loads, and the only one it loads is a one-line stamp next to the page, which tells an open page that a newer build exists. Session text sits in a non-executing block, so it cannot run as code.
- The session's text, and short excerpts of the project's other sessions for their overviews, reach the model the same way your conversation does: same account, same provider, after common secret formats are removed and IPv4 addresses and emails are masked.
- To pass on a run's report as it is, the plugin adds a hook that looks at each message sent to Claude Code, in memory, for treesight's own completion notice. It keeps nothing, sends nothing, and lets every other message through untouched.
- treesight sends nothing anywhere else. Its ledger (in `~/.local/share/treesight/` by default) stays after you uninstall the plugin; delete that folder and `~/.cache/treesight` to remove what treesight kept.

## Time and cost

Extraction counts against your Claude Code plan. treesight favours finding every open item over speed, so it runs at xhigh effort with your session's model. Measured on 2026-10-16 with Opus 5.5, as API-price equivalents: a 15-prompt session took 3.1 minutes ($0.64), and a 73-prompt session with 7 compactions took 21 minutes ($8.50) and found all 17 items on that session's own last to-do list. Later runs read only what is new, and a run with nothing new still takes a few short model requests (18 to 44 seconds in testing). The first run in a project also writes overviews of its other sessions: with 14 of them, a 9-prompt session took 7.0 minutes ($2.07) on 2026-10-23, and 5.6 minutes ($1.25) on 2026-10-21, before overviews existed (single runs). All measurements: [docs/design.md](docs/design.md#6-known-limits-and-what-remains-to-verify).

## Limitations

- Extraction is not deterministic, so the ledger keeps the first result rather than redrawing it.
- The page waits for the model's first reply before it opens; once in testing that took 3.4 minutes.
- The run's report comes back to your conversation. The plugin's hook asks Claude to pass it on as it is, which a model can still ignore; where the hook does not run, Claude may comment on it or check things on its own.
- Overviews of sessions without a tree are written from a short excerpt and can be wrong, so they are marked AI. They are written only by a run that has something new to read, up to 30 a run: after updating from 0.1.x, draw a session with new prompts, or one not drawn yet, to get them.
- The links into Claude Code need its `claude-cli://` handler, which Claude Code registers on your first interactive prompt. Your browser asks before it opens Claude Code; the command is typed into a new terminal and runs only when you press Enter, and if nothing opens, the page offers it to copy. Tried in Chrome and Terminal on macOS; a run that draws a tree, started from a link, has not been tried yet, nor have other browsers and systems. Sessions run with `claude -p` or the Agent SDK are listed only once drawn.
- The transcript format is internal to Claude Code and may change in any release.
- The page has a dark theme only.
- An open page updating itself is tested in Chrome only; Safari and Firefox are untested.

The rest, with numbers, is in [docs/design.md](docs/design.md#6-known-limits-and-what-remains-to-verify).

<details>
<summary><b>Compared with similar tools</b> (checked on 2026-10-15)</summary>

| Tool | What it does | What treesight adds |
|---|---|---|
| Claude Code agent view, desktop sidebar, Projects | Show what each session is doing now: running, needs your input, done. Projects' "Waiting on you" covers only cloud threads. | What each session got done, and what is still open across sessions, from the transcripts. |
| [loose-ends](https://github.com/MiguelProz/claude-loose-ends) | A Claude Code mod that proposes unfinished items from the current conversation, quoted literally, and closes one only when you confirm with the sentence that proves it. | The same quote rule across every session of a project, plus who you wait on, for how long, and what is blocked, and the session tree. |
| [openloops](https://github.com/thorwhalen/openloops) | Lists what is owed and blocked, with day counts, from GitHub issues; session summaries without a model. | Open items taken from what was said in the sessions. |
| [alluvia](https://github.com/dylanp12/alluvia) | A Claude Code plugin that extracts decisions with verbatim, string-matched quotes and lists unresolved questions; uses your configured LLM provider and API key. | A tree per session and the project-wide open list, using Claude Code itself. |
| [context-visualizer](https://github.com/Abudulaz/context-visualizer) | Draws typed milestones from the transcripts, linked back to the source; needs an OpenRouter key. | Open items, and no extra key. |

</details>

## Help

Questions, ideas and bugs: [open an issue](https://github.com/kuk1song/treesight/issues/new/choose); the bug form asks you not to paste anything from your sessions. For a security problem, see [SECURITY.md](SECURITY.md).

## Contributing

Tests, checks, pull requests and releases are in [CONTRIBUTING.md](CONTRIBUTING.md); the design and its reasons are in [docs/design.md](docs/design.md), and the data formats in [schema/](schema/).

## License

[MIT](LICENSE).

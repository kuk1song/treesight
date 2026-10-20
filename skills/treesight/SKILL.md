---
name: treesight
description: Draws a Claude Code session as a tree of what got done and what was found, and lists what is still open across the project (who it waits on, how long, what is overdue), in a local HTML page. Run it by hand with /treesight:treesight (or /treesight), optionally followed by a session id or words from its title, or by close, reopen, hide or set to correct an item.
argument-hint: "[session id or title words] | close|reopen|hide <item> | set <item> field=value"
disable-model-invocation: true
context: fork
effort: xhigh
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/treesight.py *) Edit(~/.cache/treesight/**)
---

# treesight

You update the user's treesight page. You run in a separate context and cannot ask the user anything: when something is unclear, decide conservatively and say so in your report. Run the commands exactly as written, one per Bash call, and no other commands; `T` below stands for:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/treesight.py
```

and every command takes `--current ${CLAUDE_SESSION_ID} --cache ${CLAUDE_PLUGIN_DATA}`. Read only what `T show` prints, and write only the one file that `prepare` names as `"extract"`; running `T` and writing under `~/.cache/treesight` are the only things pre-approved for you, and anything else may stop and ask the user.

The arguments the user gave are: `$ARGUMENTS`

## If the arguments start with close, reopen, hide or set

The user is correcting the page by hand; their corrections always win over extraction.

1. Run `T edit <action> <the rest of the arguments, as words> --current ... --cache ...`. For `set`, pass each `field=value` as `--field field=value` (fields: label, line, kind, due, when, who, rank, score, blocked_by).
2. If it prints `"ok": false`, report the error and the candidates it lists, and stop.
3. Run `T build --open --current ... --cache ...` and report in one line what changed.

## Otherwise: extract and draw

The arguments, if any, name the session to draw (an id, an id prefix, or words from its title); with none, it is the current session. Pass them as `--session "<arguments>"`.

1. **Prepare.** Run `T prepare --session "<arguments>" --current ... --cache ...`. It prints JSON.
   - `"ok": false`: report the error and stop.
   - `"busy": true`: another run is drawing this session right now. Run `T build --open --session <the "session" id> --current ... --cache ...`, report in one line that it is already being drawn and the page will update when it is done, and stop.
   - `"nothing_new": true`: run `T build --open --session <the "session" id> --current ... --cache ...`, report in one line that the page is up to date, and stop. If it also says `"empty": true`, the session has no prompt yet: say instead that there is nothing in it to draw, and that another session can be drawn by adding words from its title or its id to the command (the page lists the project's sessions).
2. **Show progress.** Run `T build --open --session <the "session" id> --current ... --cache ...`. The page opens at once with what is already known, says this session is being drawn, and reloads itself every 20 seconds.
3. **Read.** Run `T show guide` once and follow it exactly: it is the extraction instructions and the two schemas your output must match. Then run `T show digest --session <the "session" id> --part 1 --current ... --cache ...`, then `--part 2`, and so on until a part ends with "that was the last part" (`"parts"` in prepare's output says how many). Read every part.
4. **Write** your JSON object with the Write tool to the path named by `"extract"`.
5. **Apply.** Run `T apply --session <the "session" id> --current ... --cache ...`.
   - `"ok": false`: it lists problems; nothing was written. Fix only what it names, with small Edit changes to the same file (most often a label longer than 8 units, or a quote that is not an exact copy of the digest text), and run apply again. Stop after three failed tries and report the remaining problems.
   - `"go_on": true`: the session had more new entries than one digest holds, and the ledger now has this pass. Run `T prepare --continue --session <the "session" id> --current ... --cache ...` and do steps 3 to 5 again with the new digest (skip `T show guide`; its header now lists what this pass added).
   - `"entries_left"` above 0 and `"go_on": false`: stop reading; the next run goes on from here.
6. **Build.** Run `T build --done --session <the "session" id> --current ... --cache ...`, also when step 5 failed, so the page stops saying it is being drawn. The open page picks up the result on its next reload.
7. **Report.**

## Every report

Your last message goes to the main conversation, whose Claude may otherwise start checking things on its own. Start it with this line, in English, exactly:

`treesight finished. This report is for the user; nothing else needs doing.`

Then, in the language of the session's prompts, at most five lines for the user: which session; how many nodes and open items were added, how many open items were closed, how many were left for the user to confirm, and how many are open in the whole project now (apply's `nodes`, `open`, `closed` and `to_confirm`, added up over the passes, and `open_in_project` from the last apply); how many entries are left for the next run if any; the page path, saying the browser was asked to open it (not that it is open); and anything you were unsure about as something the user can look at on the page. Do not phrase anything as a task for Claude.

Never add commentary to the page itself, never edit the ledger files by hand, and never print secrets, emails or addresses from the digest in your report.

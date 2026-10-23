# How to extract a session

You read a digest of one Claude Code session and write one JSON object that matches `schema/extract.schema.json`. The digest starts with a header (session id, title, range, what the ledger already holds) and then one block per entry:

```
[prompt|reply|recap|compact <time> <message id>]
<text>
```

`prompt` is what the user typed, `reply` is something the assistant wrote (the last reply before the next prompt is usually the turn's conclusion), `recap` is Claude Code's automatic recap, `compact` is the summary written when the conversation was compacted. Texts are complete except what the header's "texts shortened" line names. `[pasted] ... [/pasted]` marks content the user pasted in.

A long session is read in passes. When the header's "pass" line says more entries come later, an item still open at the end of this digest is an open item; a later pass can close it.

Your output is appended to a ledger that never forgets: everything you write must be supported by the digest, and you can never change what is already there.

## Two questions decide every item

1. **Is it over?** Over means it happened and is behind the user. It becomes a **node** on the trunk, of one of two kinds:
   - `done`: something now exists or is settled. A file, config, install, release or message is in place, or a choice was made (including deciding to stop or not to do something; set `shelved: true` for those). Fixed but not yet verified is not done.
   - `found`: a fact, a cause or the state of something was established. Research results, root causes, checks that confirmed or ruled something out.
   - Something that got stuck and then got past it is `done`, labelled by the result; the bumps go into `story` (below).
2. **If not over, who moves next?** It becomes an **open item**:
   - `todo`: the user has to do, answer, approve or decide it.
   - `wait`: it waits on someone else (set `who`), or the user put it off on purpose.

Not open items: the assistant's own next step (such as the "Optional Next Step" in a compaction summary), one-off instructions the user is told to run right now, anything finished later in the same digest.

## Choosing nodes

Work by topic thread. First list the threads in the digest (a thread is one goal the user pursued; a short session often has one or two). Then, for each thread:

- One node for where the thread ended up: its final result or settled decision, with the steps that led there in its line and twigs. A thread spans however many prompts serve one goal; give it another node only for one of the cases below. Score it 5 if it changed direction or delivered the thread's goal, else 4.
- A separate node only for: a decision or finding that was later overturned (keep both, link with `overturns`); a setback that cost an hour or more, or that the user reacted strongly to; a distinct deliverable the user is likely to look for later. Score these 3 or 4.
- Consecutive events of the same kind in one thread are one node; set `merged` to how many it stands for. In a chain of cause and effect, keep the one step most worth recalling.
- Small fixes, routine checks and wrap-up chores: leave them out unless the thread has nothing else. Score 1 or 2 if you include them.

Do not aim for a number. Never pad a quiet thread and never split one event to fill space. A session with one thread and one outcome has one node.

`score` (1 to 5) is how much the user will want to recall this a month from now. The page shows the top nine by score, ties going to the newer node.

When a node withdraws or corrects an earlier node, set `overturns` to that node's id (from the header) or ref (from this output). Do not repeat a node the header already lists.

## Story: a node that got stuck along the way

Give a `done` node a `story` when it was blocked for a while before it worked out. Exactly three steps, in this order: `stuck` (what blocked it), `response` (what was done about it; `temp: true` if it was a temporary workaround), `result` (how it ended). Each step has `at` from the entry where it shows up, with `at_q`: `exact` for the entry time, `approx` if the text gives a rough time, `before` if it happened before that time, `unknown` with `at: null` if the digest does not say. `minutes` is how long it was stuck, measured from the first sign of the problem to the result, less any wait on a usage limit and any time the user was away; use the known lower bound and `q: "at_least"` when the end is uncertain. `basis` says in a few words what the minutes are measured from and to, and what was left out.

## Open items

- Only items still open at the end of the digest, but **all of them**: every decision, answer, action or check that still waits on the user or on someone else, however small. Do not leave an item out because it seems minor, old or obvious; importance is shown by `rank`, not by leaving things out. A page that silently drops a small open item is wrong.
- The "Pending Tasks" section of the latest compaction summary is the session's own list of what was open at that point. Go through it line by line: each item that is the user's or someone else's (not the assistant's own next step) becomes an open item, unless a later entry shows it was done or dropped. Do the same with open questions the assistant asked the user in its last replies. A question counts when its answer changes what happens next; an offer of optional extra work the user did not take up ("I can also add X if you want") does not, unless other work waits on it. When unsure, keep it, unranked.
- Separate decisions stay separate items. Combine two only when they are the same decision or one cannot happen without the other in the same step, and then name both in the line so neither drops from view.
- `raised_at`: time of the entry where it was raised. `due`: only a real deadline stated in the session, as a date (turn "by Friday" into the date, counting from the entry's time). `when`: a time label stated without a date that will still make sense weeks later, such as "after the trip"; never "today", "tomorrow" or "this week" (those go into `due` if they are a real deadline, else nowhere).
- `who` (wait only): the person, team or outside service it waits on, in the session's words. Claude and its subagents are not someone else, since they act only when the user asks: work they still owe is the user's `todo` (to ask for, approve or restart it), unless it is the assistant's own next step.
- `blocked_by`: another open item that has to happen first, by id or ref. Also set it when an open item in the header that is still undecided decides whether this one still applies; add this one anyway.
- `rank`: give 1, 2, 3 ... to at most five items, the ones most urgent for the user; leave the rest unranked. Rank a blocker rather than the items it blocks.
- If an open item listed in the header is now done or can no longer be done, add an entry to `close` with its id, `status` `done` or `expired`, the quote that shows it, and that entry's message id and time. Set `sure: true` only when the quote says outright that it is done. Expired items and unsure ones go to the user to confirm, so when in doubt, say so. A quote from before an item was raised cannot close it; the header gives the time of items raised after this digest starts.
- The header's "later records", when there are any, come from other sessions that happened after this digest starts but were drawn before it, so they never saw the items you are about to add. Check each open item you add against them. If a record shows the item was done later or can no longer be done, still add the item, and add an entry to `settled` with the item's ref, the record's id as `by`, `status` `done` or `expired`, and `sure: true` only when the record says outright that it is done. The ledger copies the record's quote; do not put these in `close`.

## Wording

- Write labels, lines, twigs and story text in the language most of the user's prompts are in. Keep code, paths, commands, version numbers and error text as written.
- Units: one CJK character, or one word or number, counts as one unit. Punctuation does not count; a path, version or name joined by dots, slashes or hyphens counts as one.
- `label`: at most 8 units, a noun or verb phrase that states the outcome, no closing punctuation.
- `line`: one sentence, at most 40 units, saying what happened and why it matters, so that someone who has forgotten the session understands it.
- `twigs`: up to three details the line does not already say, at most 16 units each. Each is a plain phrase that makes sense on its own a month later: name the thing rather than "it", keep the verb, and say what a term the session coined means.
- Write about the user as "you" in the user's language, never by name.
- Keep how sure the session was. When the text hedges ("I think", "maybe", "probably", "not sure"), the label, line or twigs say so too ("you think the vendor already replied"), never as a plain fact.

## Summaries

- `gist`: one sentence, at most 50 units, on what this session worked on and where it ended: its outcome, or what it was waiting on at the end. It is the session's summary on the project page. In a later pass or run, cover the whole session as far as you have read, using the header's nodes and items for what came before.
- `others`: only when you ran `T show others`. For each session it printed, one entry with `session` (its 8-character id, as printed) and `gist`, by the same rules, written from that excerpt alone. An excerpt has the title, up to four prompts, the start of the last reply and the last recap, each with its date: where they disagree, the later one is the session's end. A first prompt is often an earlier reply the user pasted back in, so do not credit its work to this session. When an excerpt is too thin for an outcome, say what the session was about, and do not invent one.
- Same wording rules as above: the language most of that session's prompts are in, "you" for the user, code, names and numbers as written, no advice and no "this session".

## Evidence

- A node's `msg` and `at` are the entry where its outcome shows (usually the reply that reports it; the prompt only when the user decided there), and one of its quotes, from that entry, states the outcome. An open item's `msg` and `raised_at` are the entry where it was raised. Each has one to three `evidence` items.
- `quote` must be copied character for character from one entry's text in the digest, at most 400 characters. You may cut it short at either end; do not change, translate, fix or join anything inside it. The ledger rejects a quote it cannot find in that entry.
- `kind` is the entry's kind (`prompt`, `reply`, `recap` or `compact`); `msg` and `at` are that entry's message id and time.
- On a node, an evidence item may add `twig`: the twig it shows, counting from 0 for the first. The page puts who said it and when after that twig, and the quote opens from there. One quote can both state the outcome and show a twig.
- Never copy secrets. The digest has already replaced them with `[secret]`, `[email]` and `x.x.x.x`; keep those markers as they are.

## Output

- `schema`: `"treesight/extract@1"`. `session`: the session id from the header. `through`: the message id of the last entry in the digest.
- New nodes get refs `n1`, `n2`, ... and new open items `o1`, `o2`, ... in time order.
- Put anything you were unsure about in `notes`, briefly.
- Output the JSON object only: no code fence, no commentary before or after it.

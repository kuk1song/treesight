#!/usr/bin/env python3
"""The plugin's UserPromptSubmit hook: when a treesight run's completion notice reaches the main conversation, ask
Claude there to show the user the report as it is, so the conversation does not turn it into a review of its own.

Claude Code runs this hook on every prompt of a session where the plugin is enabled, including the notice a background
skill sends when it finishes (https://code.claude.com/docs/en/hooks.md, UserPromptSubmit). It reads the prompt from
stdin and keeps nothing. Only a notice that a /treesight:treesight run completed with a report that starts with the
skill's fixed first line gets an answer: the report from its third line on, inside an instruction added to Claude's
context. Anything else, an error included, prints nothing and exits 0, so the prompt goes on as it would without the
hook. Started with python3 -I -S; what that costs per prompt depends on the python3 it finds (docs/design.md).

Tested on Claude Code 2.1.299 on 2026-10-26: a skill's own frontmatter hook never ran for a forked skill, so this is a
plugin hook; blocking the notice instead shows the user "UserPromptSubmit operation blocked by hook:" in warning
colours, while this instruction gave a reply of exactly the report.
"""
import json
import re
import sys

HEAD = "treesight finished. This report is for the user; nothing else needs doing."
_NOTICE = re.compile(r'<summary>Agent "/(?:treesight:)?treesight[ "]')
_RESULT = re.compile(r"<result>(.*?)</result>", re.S)
ASK = ("This notice is a treesight run's report, written for the user, who does not see it until you show it. "
       "Reply with exactly the text between <<< and >>>, word for word, and nothing else: no commentary, "
       "no questions, no tool use.")


def answer(prompt):
    """The hook's output for one prompt, or None to let it through untouched."""
    if not prompt.lstrip().startswith("<task-notification>") or "<status>completed</status>" not in prompt:
        return None
    if not _NOTICE.search(prompt):
        return None
    m = _RESULT.search(prompt)
    lines = (m.group(1) if m else "").strip().splitlines()
    if not lines or lines[0].strip() != HEAD:
        return None
    body = "\n".join(lines[1:]).strip()
    if not body:
        return None
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ASK + "\n<<<\n" + body + "\n>>>"}}


def main():
    try:
        # bytes in, ASCII out: whatever locale the hook runs under, Chinese text neither fails to decode nor to print
        out = answer(json.loads(sys.stdin.buffer.read().decode("utf-8", "replace")).get("prompt") or "")
        if out:
            sys.stdout.write(json.dumps(out))
    except Exception:       # never in the way of a prompt
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

---
name: claude-mem-handoff
description: Use at the end of a working session, before context bloat, or when switching tasks. Snapshots the active task (intent, decisions, open questions, recent memories, context handles) to a markdown file under .claude-mem/handoffs/, so a fresh session can resume(task_id) without re-explaining state. Triggers on "let's pick this up later", "I'm going to start a new session", "snapshot this task".
---

# claude-mem-handoff

claude-mem tracks tasks. When you wrap up work — or anticipate hitting a
context-budget wall — call `handoff(task_id)` to render the current state to
a markdown snapshot. In the next session, the user (or you) calls
`resume(task_id)` to load it back at ~2-4k tokens.

## When to handoff
- End of session, work isn't done.
- Context is filling up and you want a clean restart.
- Switching to a parallel task.

## What gets captured
- The task's intent and acceptance criteria.
- Decisions you've made this session (links to memory units).
- Open questions you've raised.
- The pre-sized bundle of context handles you've been working with.
- The most recent memory writes (last 10).

## What does NOT get captured
- Files you read but didn't `remember()` anything about.
- Reasoning steps. (Only durable conclusions land in memory.)

## Worked example

You finish a refactor halfway. Call `handoff(task_id="task://task/abc")`. The
markdown lands at `.claude-mem/handoffs/abc.md` and is git-trackable. Next
session: `resume(task_id="task://task/abc")` and you're back at the same point
with a 4k-token bundle.

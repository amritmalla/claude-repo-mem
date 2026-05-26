---
name: claude-repo-mem-recall
description: Use BEFORE Grep/Read when looking for code, symbols, documentation, or prior decisions in this repo. Calls recall(query) on the local claude-repo-mem MCP server; returns ranked, budgeted, tiered results in one round-trip. Triggers on "find X", "where is Y defined", "show me the auth code", "what did we decide about Z".
---

# claude-repo-mem-recall

You have a local claude-repo-mem MCP server with the entire repo pre-indexed (code,
docs, memory). It runs hybrid lexical + semantic retrieval in <500ms and returns
content already summarized at the right tier for your budget.

## When to call recall
- "Where is `<symbol>` defined?" — call `recall(query="<symbol>")` before opening files.
- "How does authentication work?" — `recall(query="authentication", scopes=["backend/auth"])`.
- "What did we decide about token signing?" — `recall(query="token signing decision")`.

## When NOT to call recall
- Reading a file you already have a path for — just use Read.
- Verifying a recent edit (recall lags by one indexer pass) — use Read.
- Looking at files outside this repo.

## Worked example

User: "How do refresh tokens work in this codebase?"
You: call `recall(query="refresh token flow", scopes=["backend/auth"], budget=4000)`
Response: 3-5 ranked items with T2 summaries, plus a few T1 headers. Use the
handles to drill in with `trace` or `expand` if needed.

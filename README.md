# claude-mem

Contextual memory and retrieval engine for Claude Code. Local-first MCP server that gives Claude durable project memory and hierarchical retrieval over a single repo's code, docs, and prior decisions.

**Status:** Phase 4 — Java/Go/Rust parsers, Django/Express/React synthesizers, install-hooks, background queue.

## Install

```bash
pip install -e ".[dev]"
```

## Quick start

```bash
cd your-repo
claude-mem index                # full reindex
claude-mem doctor               # show index size
claude-mem serve --watch        # MCP server with background incremental reindexing (default)
claude-mem serve --no-watch     # MCP server, no file watcher
claude-mem install-hooks        # post-commit reindex (alternative to --watch)
claude-mem doctor               # diagnostics: layer counts, T2 coverage, counters
claude-mem distill --yes        # extract durable memories from latest session
```

Connect Claude Code to the server via your MCP config.

## Tools

Phase 1 (retrieval):
- `recall(query, budget=3000)` — ranked hybrid search with budgeted tiered fill
- `trace(seed_handles, depth=2, budget=8000)` — graph traversal from a seed handle
- `expand(handle, tier)` — drill into one unit at a specific tier (T0/T2/T1)

Phase 2 (memory, tasks, observability):
- `remember(fact, scope, kind?)` — write a durable memory entry as `.claude-mem/memory/<scope>/<slug>.md`
- `forget(handle)` — tombstone a memory unit (file preserved, frontmatter updated)
- `scopes()` — list known scopes with unit counts
- `stats()` — index size, layer breakdown, tool-call counters
- `plan_task(intent)` — LLM-decomposes a task into 2-6 independent child tasks
- `tasks(status?, scope?)` — list persisted tasks

Phase 3 (continuity):
- `handoff(task_id)` — snapshot a task to `.claude-mem/handoffs/<id>.md` and create a `task_snapshot` unit
- `resume(task_id, budget=4000)` — load the latest snapshot + a budgeted bundle of its context handles

LLM access uses MCP sampling by default (`CLAUDE_MEM_LLM=mcp`). For the CLI `distill`
command, set `ANTHROPIC_API_KEY` to use the Anthropic API directly.

Companion skills are shipped in `plugin/skills/` — `claude-mem-recall`, `claude-mem-trace`,
`claude-mem-handoff` — telling Claude when to reach for these tools.

Languages indexed: Python, JavaScript, TypeScript, Markdown, Java, Go, Rust.
Synthesizers: Flask / Django / Express routes, Python imports, React `useState` hooks.

## Architecture

See `docs/specs/2026-05-25-claude-mem-design.md`.

## Tests

```bash
pytest                  # fast tests
pytest -m slow          # includes bge-small embedder tests (downloads model)
```

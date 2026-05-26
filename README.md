# claude-mem

Contextual memory and retrieval engine for Claude Code. Local-first MCP server that gives Claude durable project memory and hierarchical retrieval over a single repo's code, docs, and prior decisions.

**Status:** Phase 1 — substrate, retrieval, traversal. Memory writes, tasks, and handoff land in Phase 2/3.

## Install

```bash
pip install -e ".[dev]"
```

## Quick start

```bash
cd your-repo
claude-mem index                # full reindex
claude-mem doctor               # show index size
claude-mem serve                # run MCP server on stdio
```

Connect Claude Code to the server via your MCP config.

## Tools (Phase 1)

- `recall(query, budget=3000)` — ranked hybrid search with budgeted tiered fill
- `trace(seed_handles, depth=2, budget=8000)` — graph traversal from a seed handle, full source for connected nodes in one round-trip
- `expand(handle, tier)` — drill into one unit at a specific tier (T0/T2/T1)

## Architecture

See `docs/specs/2026-05-25-claude-mem-design.md`.

## Tests

```bash
pytest                  # fast tests
pytest -m slow          # includes bge-small embedder tests (downloads model)
```

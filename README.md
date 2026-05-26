# claude-mem

> Durable, hierarchical, repo-scoped memory for Claude Code. Local-first MCP server.

`claude-mem` indexes your repository — code, docs, and your own accumulated decisions — into a SQLite database with hybrid lexical + vector retrieval, then exposes it to Claude Code as 11 MCP tools. The point: Claude stops grepping. It calls `recall(query)` and gets back ranked, budgeted, tier-aware results in one round-trip.

Memory is durable. Decisions you `remember()` land as committed markdown files under `.claude-mem/memory/`. Tasks survive session boundaries via `handoff()` / `resume()`. The index keeps itself warm via a file watcher or a git post-commit hook.

**Status:** v0.1, feature-complete. 5 development phases shipped, 255 tests passing. ~3.5k LoC of source.

---

## Why

LLM coding assistants spend most of their context budget rediscovering code. They grep, they read, they re-read. claude-mem replaces that with a structured index: each unit (function, class, doc section, decision) has three tiers — full source (T0), LLM summary (T2), and a single-line header (T1) — and retrieval picks the right tier to fit your budget.

The retrieval substrate is a graph: routes connect to handlers (Flask / Django / Express synthesizers), Python imports become edges, React `useState` setters tag their containing components. One `trace(seed_handle)` call surfaces the connected subgraph in full source.

Memory is the second half. `remember(fact, scope, kind="decision")` writes a markdown file with YAML frontmatter that's both human-readable and git-trackable. `handoff()` snapshots an in-flight task — intent, decisions, open questions, context handles — so the next session starts at ~2-4k tokens fully oriented.

---

## Install

```bash
pip install claude-mem
```

Requires Python 3.11+. Development install:

```bash
git clone https://github.com/amritmalla/claude-mem
cd claude-mem
pip install -e ".[dev]"
```

---

## Quick start

```bash
cd your-repo
claude-mem index               # build the index (downloads bge-small on first run, ~90MB)
claude-mem doctor              # verify: units, by_layer, T2 coverage, counters
```

To expose it to Claude Code, drop a `.mcp.json` in your repo root:

```json
{
  "mcpServers": {
    "claude-mem": {
      "command": "claude-mem",
      "args": ["serve", "--watch"]
    }
  }
}
```

Claude Code will auto-launch the server on workspace load. The `--watch` flag runs an incremental file watcher (debounced 750ms) so the index stays current as you edit.

Prefer not to run the watcher? Install a git hook instead:

```bash
claude-mem install-hooks       # writes .git/hooks/post-commit
```

---

## Tools

All 11 tools are exposed over the MCP protocol. Group by intent:

**Retrieval**
- `recall(query, budget=3000, scopes?, layers?)` — hybrid lexical + vector search with budgeted tier-aware fill.
- `trace(seed_handles, depth=2, budget=8000)` — graph traversal from a seed; returns full T0 source for connected nodes in one round-trip.
- `expand(handle, tier="t0"|"t2"|"t1")` — drill into one unit at a specific tier.

**Memory**
- `remember(fact, scope, kind="fact"|"decision"|"preference"|"convention", confidence?, supersedes?)` — write a durable memory entry as `.claude-mem/memory/<scope>/<slug>.md`.
- `forget(handle)` — tombstone a memory unit (frontmatter updated, file preserved).
- `scopes()` — list known scopes with unit counts.

**Tasks & continuity**
- `plan_task(intent, parent_id?, context_handles?)` — LLM-decomposes into 2-6 independent child tasks via MCP sampling.
- `tasks(status?, scope?, since_days?)` — list persisted tasks with filters.
- `handoff(task_id)` — snapshot a task to `.claude-mem/handoffs/<id>.md` + write a `task_snapshot` unit.
- `resume(task_id, budget=4000)` — load latest snapshot + a budgeted bundle of its context handles.

**Observability**
- `stats()` — index size, layer breakdown, tool-call counters.

---

## CLI

```text
claude-mem index [--embedder NAME] [--no-embed] [--reset]
claude-mem serve [--watch | --no-watch]
claude-mem doctor                              # layer counts, T2 coverage, counters
claude-mem install-hooks [--force]             # git post-commit reindex
claude-mem distill [--yes] [--transcript PATH] # extract durable memories from a transcript
claude-mem bench   --fixture queries.yaml [--k 5] [--no-embed]
```

---

## Languages and synthesizers

| Language | Parser | Notes |
|---|---|---|
| Python | tree-sitter | classes, methods, functions, docstrings |
| JavaScript / TypeScript | tree-sitter | functions, classes, methods, JSX |
| Java | tree-sitter | classes, interfaces, methods, constructors |
| Go | tree-sitter | funcs, methods, structs, interfaces |
| Rust | tree-sitter | fn, impl methods, structs, traits |
| Markdown | markdown-it | sections by heading hierarchy |

Synthesizers add cross-file edges on top of parser output:

- **Flask** `@app.route(...)` → handler.
- **Django** `path(...)` / `re_path(...)` → handler (resolves dotted refs against `views.py`).
- **Express** `app.METHOD(url, handler)` → same-file handler.
- **Python imports** → cross-module edges.
- **React hooks** — `useState` setter calls emit `mutates_state_of` edges on the containing component.

---

## Embedders

Default is local `bge-small` (384d, CPU). Switch via `--embedder` or `CLAUDE_MEM_EMBEDDER`:

```bash
export OPENAI_API_KEY=sk-...
claude-mem index --embedder openai --reset    # text-embedding-3-small, 1536d

export VOYAGE_API_KEY=vy-...
claude-mem index --embedder voyage --reset    # voyage-3-lite, 512d
```

`--reset` is required when changing embedders — the vector dimension is baked into the SQLite vec0 table at schema creation.

---

## LLM access

Tools that need an LLM (`plan_task`, summarizer backfill, distill) use MCP sampling by default — the host (Claude Code) supplies the model via the standard sampling protocol.

For CLI tools that run outside an MCP session (`distill`), fall back to the Anthropic API by setting:

```bash
export CLAUDE_MEM_LLM=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## Where things live

```
.claude-mem/
├── db.sqlite              # the index (gitignored)
├── memory/<scope>/*.md    # remember() writes — committed source of truth
├── handoffs/<task>.md     # handoff() snapshots — committed, resumable
└── blobs/                 # cached embeddings (gitignored)
```

Memory markdown files have YAML frontmatter:

```markdown
---
kind: decision
scope: backend/auth
confidence: 0.9
created_at: 2026-05-26T10:00:00Z
---

We chose RS256 over HS256 so the API gateway can verify tokens without
holding the signing key.
```

Re-indexing preserves these — they're the source of truth, the SQLite index is derived.

---

## Companion skills

`plugin/skills/` ships three SKILL.md files that teach Claude when to call which tool:

- `claude-mem-recall` — use BEFORE `Grep` / `Read`.
- `claude-mem-trace` — use AFTER recall when you have a seed handle.
- `claude-mem-handoff` — use at end of session, before context bloat.

Drop them into any Claude Code plugin tree to make the tool-use rules ambient.

---

## Integration with claude-full-stack-2.0

The [claude-full-stack-2.0](https://github.com/amritmalla/claude-full-stack-2.0) plugin ships a `memory-management` skill that documents how to wire `claude-mem` into projects built with that workflow. See `INTEGRATION.md` and `skills/architecture/memory-management/` in that repo.

---

## How it works

**Substrate.** A SQLite database with:
- `unit` — addressable items (code symbols, doc sections, memories, tasks).
- `relation` — typed edges between units (`calls`, `imports`, `route_to`, `child_task`, `mutates_state_of`, …).
- `unit_fts` — FTS5 mirror of headers + summaries for lexical search.
- `unit_vec` — sqlite-vec virtual table for ANN search.

**Retrieval.** Hybrid: FTS BM25 ⊕ vector cosine, reciprocally-ranked, then a budget-aware fill that picks T0 / T2 / T1 per unit to fit your token cap. Overflow handles are returned for explicit drill-in.

**Memory.** Markdown files are the source of truth. The indexer treats `.claude-mem/memory/*.md` like any other docs source — parse frontmatter, derive scope, write a `memory` layer unit. `forget()` tombstones via a sentinel handle so the FK constraint is satisfied.

**Tasks.** Units of `layer=task, kind=task` with structured JSON metadata. `child_task` relations build the tree. `handoff()` renders a markdown snapshot + writes a `task_snapshot` unit pointing at it.

**Watcher.** `watchdog.Observer` + a 750ms `PathDebouncer` → `incremental_reindex(paths)`. Reindex jobs run on a single-worker `BackgroundQueue` so the watcher callback never blocks.

Full design in [`docs/specs/2026-05-25-claude-mem-design.md`](docs/specs/2026-05-25-claude-mem-design.md). Per-phase plans under [`docs/plans/`](docs/plans/).

---

## Development

```bash
pip install -e ".[dev]"
pytest                    # 255 fast tests
pytest -m slow            # +5 slow tests (real watchdog FS events)
```

Phase tags mark each shipped milestone:

| Tag | Scope |
|---|---|
| `phase-1-complete` | Substrate, parsers, hybrid retrieval, `recall` / `trace` / `expand` |
| `phase-2-complete` | Memory layer, `remember` / `forget` / `scopes` / `stats` / `plan_task` / `tasks`, distillation |
| `phase-3-complete` | `handoff` / `resume`, file watcher, companion skills |
| `phase-4-complete` | Java / Go / Rust parsers, Django / Express / React synthesizers, install-hooks, background queue |
| `phase-5-complete` | Pluggable embedders (OpenAI / Voyage), queue-driven summarization, bench harness, distill UX |

---

## License

MIT.

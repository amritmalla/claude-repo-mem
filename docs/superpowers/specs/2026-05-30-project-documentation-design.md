# Project Documentation — Design

**Date:** 2026-05-30
**Status:** Approved
**Topic:** Add user- and contributor-facing documentation for `claude-repo-mem`

## Goal

The repo has a strong README, a CHANGELOG, a design spec, and five phase plans, but
no dedicated reference, internals, usage, or contributor documentation. Add four
documents, as plain markdown (no build tooling), to cover those gaps.

Format decision: **plain markdown under `docs/`** — matches the existing
`docs/specs/` and `docs/plans/` convention, adds zero tooling debt, and suits a
local-first 0.1.x beta. A docs site (e.g. MkDocs) is explicitly deferred (YAGNI);
the content can graduate to one later with no rewrite.

## Layout

```
docs/
  README.md          # index: what each doc is, who it's for
  tools.md           # MCP tool reference
  architecture.md    # internals for contributors
  usage.md           # task-oriented user guide
CONTRIBUTING.md      # repo root (GitHub convention)
```

- The main `README.md` gains a short "Documentation" section linking to these.
- Existing `docs/specs/` and `docs/plans/` are left untouched as the historical
  design record.

## Documents

### 1. `docs/tools.md` — Tool reference

Reference for the 11 MCP tools. One subsection per tool, grouped by purpose:

- **Retrieval:** `recall`, `trace`, `expand`
- **Memory:** `remember`, `forget`, `scopes`
- **Tasks & handoff:** `plan_task`, `tasks`, `handoff`, `resume`
- **Diagnostics:** `stats`

Each entry contains: one-line purpose, parameters, return shape, and a "when to
use" note. Parameter and return details are taken from each tool's actual
`inputSchema` in `src/claude_repo_mem/tools/<tool>.py` so the reference matches the
implementation. The document opens with the recall-before-Read /
trace-before-expand guidance from the server instructions.

### 2. `docs/architecture.md` — Internals

Contributor-facing walk-through following the data flow:

1. **walker** — file discovery (`indexer/walker.py`)
2. **parsers** — tree-sitter per language (python/js-ts/java/go/rust) plus
   markdown and `memory.md` (`indexer/parsers/`)
3. **synthesizers** — framework-aware relations: django/flask/express routes,
   react hooks, imports (`indexer/synthesizers/`)
4. **summarizer** — LLM summarization tiers (`summarizer/`)
5. **DB schema** — units, relations, layers (`code`/`docs`), sqlite-vec vectors
   (`db/schema.py`, `db/repository.py`)
6. **retrieval** — `recall` (hybrid lexical + vector, ranker, fill), `trace`
   (graph walk over relations) (`retrieval/`)
7. **embeddings** — bge-small default, openai/voyage optional (`embeddings/`)
8. **incremental watcher** — debounced re-index on file change
   (`indexer/incremental.py`, `queue/background.py`)

Closes with a short description of the `.claude-repo-mem/` state directory
(db.sqlite, blobs, handoffs, memory, scopes.yml).

### 3. `docs/usage.md` — User guide

Task-oriented guide beyond the README quick-start:

- **Install** and first index (`index`, `doctor`)
- **Wire into Claude Code** via `.mcp.json`, including the `--root` flag and why
  it matters (Claude Code launches MCP servers from a system directory, not the
  repo)
- **Configuration:** `CLAUDE_REPO_MEM_EMBED` env var, embedding backends
  (bge-small/openai/voyage), LLM backends (anthropic_api / mcp_sampling),
  `scopes.yml`
- **Workflows:** distill durable memories from transcripts; handoff/resume across
  sessions
- **Troubleshooting:** wrong cwd → pass `--root`; empty recall → reindex; first-run
  model download
- **CLI command summary** (`index`, `serve`, `doctor`, `distill`, `bench`,
  `install-hooks`)

### 4. `CONTRIBUTING.md`

- Dev install: `pip install -e ".[dev]"`
- Running tests: `pytest`
- Project layout map (the `src/claude_repo_mem/` package tree)
- Conventions
- Version-bump / release flow as seen in commit history

## Out of scope

- A buildable/published docs site (MkDocs or similar) — deferred.
- Changes to existing `docs/specs/` and `docs/plans/`.
- API docs for internal Python functions beyond the architecture overview.

## Success criteria

- All four documents exist and render correctly as GitHub markdown.
- Tool reference matches the actual `inputSchema` of each tool.
- Architecture doc names real modules/paths that exist in the tree.
- README links to the new docs.
- A new user can go from install to a working Claude Code integration using only
  `docs/usage.md`.

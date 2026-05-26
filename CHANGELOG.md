# Changelog

All notable changes to `claude-repo-mem` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and the
project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] — 2026-05-30

First public release. Five development phases shipped, 255 tests passing.

### Substrate & retrieval

- SQLite + sqlite-vec hybrid index (lexical FTS5 + vector ANN).
- Tree-sitter parsers for Python, JavaScript / TypeScript, Java, Go, Rust;
  markdown-it for Markdown.
- Three-tier representation per unit: T0 (full source), T2 (LLM summary,
  lazy), T1 (header).
- Reciprocal-rank fusion + budget-aware tier fill on `recall`.
- Graph traversal on `trace(seed_handle, depth=2)`.
- Per-unit `expand(handle, tier)`.

### Memory & tasks

- `remember()` / `forget()` writes memory as markdown files under
  `.claude-repo-mem/memory/<scope>/<slug>.md` (committed source of truth).
- `plan_task()` LLM-decomposes intents into 2-6 independent child tasks via
  MCP sampling.
- `tasks()` filtered listing.
- `handoff()` snapshots an in-flight task to a markdown file + `task_snapshot`
  unit. `resume()` rehydrates within a budget.

### Operations

- `claude-repo-mem index` full reindex.
- `claude-repo-mem serve --watch` MCP stdio server with file watcher
  (`watchdog` + 750ms debounce → incremental reindex on a `BackgroundQueue`).
- `claude-repo-mem install-hooks` post-commit git hook.
- `claude-repo-mem doctor` reports layer counts, T2 coverage, counters.
- `claude-repo-mem distill` extracts durable memories from a Claude Code
  transcript with scope-aware dedupe.
- `claude-repo-mem bench --fixture` YAML-driven recall@k benchmark.

### Synthesizers

Framework-aware cross-file edges:

- Flask `@app.route(...)` → handler
- Django `path(...)` / `re_path(...)` → handler (dotted refs resolved against
  `views.py`)
- Express `app.METHOD(url, handler)` → same-file handler
- Python imports → cross-module edges
- React `useState` setter calls → `mutates_state_of` edges

### Pluggable embedders

- `bge-small` (local, 384d, CPU, default)
- `openai` text-embedding-3-small (1536d, requires `OPENAI_API_KEY`)
- `voyage` voyage-3-lite (512d, requires `VOYAGE_API_KEY`)
- `embedder_meta` table refuses dim mismatches without `--reset`.

### Companion skills

- `plugin/skills/claude-repo-mem-recall/`
- `plugin/skills/claude-repo-mem-trace/`
- `plugin/skills/claude-repo-mem-handoff/`

[0.1.0]: https://github.com/amritmalla/claude-repo-mem/releases/tag/v0.1.0

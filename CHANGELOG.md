# Changelog

All notable changes to `claude-repo-mem` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and the
project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- New `claude-repo-mem init` command: scaffolds `.claude-repo-mem/` and writes or
  merges a `claude-repo-mem` entry into the repo's `.mcp.json` in one step. The
  merge preserves any other `mcpServers` entries and refuses to overwrite a
  differing `claude-repo-mem` entry without `--force`. Optional `--index` runs the
  first index, `--hooks` installs the post-commit git hook, and `--embedder` /
  `--no-watch` are baked into the generated `serve` args.
- `init --target desktop` writes to Claude Desktop's global config instead of the
  project `.mcp.json`. The server is keyed by folder name (e.g.
  `claude-repo-mem-myrepo`) so multiple repos coexist, and the absolute path to the
  `claude-repo-mem` executable is resolved and baked in so Desktop always finds it.

### Fixed
- Config merging now reads existing files with `utf-8-sig`, so a `.mcp.json` saved
  with a UTF-8 BOM (common on Windows editors) is accepted instead of rejected as
  invalid JSON.

## [0.1.3] — 2026-05-30

### Added
- Added a `CLAUDE_REPO_MEM_ROOT` environment variable to pin the repo root
  explicitly without the `--root` flag (useful under MCP hosts that only expose an
  `env` block).
- Root resolution now also falls back to `CLAUDE_PROJECT_DIR` when set, for hosts
  that inject it. Note: current Claude Code builds do **not** set `CLAUDE_PROJECT_DIR`
  for spawned MCP servers nor advertise the MCP `roots` capability, so an explicit
  root (`--root` or `CLAUDE_REPO_MEM_ROOT`) remains required there.
- Full resolution order: `--root` flag → `CLAUDE_REPO_MEM_ROOT` → walk up from cwd
  → `CLAUDE_PROJECT_DIR`.

## [0.1.2] — 2026-05-28

### Added
- Added `.mcp.json` configuration file at the repository root for client auto-wiring.

### Changed
- Modified `serve` command to automatically discover the repository root if no `--root` path is provided, instead of defaulting to `Path.cwd()`.

## [0.1.1] — 2026-05-27

### Documentation

- Simplified README.md to only keep required user-facing information, removing developer-focused details.

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

[0.1.2]: https://github.com/amritmalla/claude-repo-mem/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/amritmalla/claude-repo-mem/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/amritmalla/claude-repo-mem/releases/tag/v0.1.0

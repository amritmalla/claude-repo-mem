# Contributing

Thanks for working on `claude-repo-mem`. This guide covers local setup, tests, and
the release flow. For how the system works internally, see
[docs/architecture.md](docs/architecture.md).

## Development setup

Requires Python 3.11+.

```bash
git clone https://github.com/amritmalla/claude-repo-mem
cd claude-repo-mem
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

The `dev` extra pulls in pytest, ruff, and the build/release tooling. Optional
backend extras are separate: `.[openai]`, `.[voyage]`, `.[anthropic]`.

## Running tests

```bash
pytest                       # unit + integration, excluding slow tests
pytest -m slow               # tests that download models / are expensive
pytest --cov=claude_repo_mem # with coverage
```

Test configuration lives in `pyproject.toml` under `[tool.pytest.ini_options]`:
`pythonpath = ["src"]`, `asyncio_mode = "auto"`, and `addopts = "-m 'not slow'"`,
so the default run skips tests marked `slow`. Tests are split into
`tests/unit/` and `tests/integration/`, with shared fixtures in
`tests/conftest.py`.

## Linting

```bash
ruff check src tests
```

## Project layout

```
src/claude_repo_mem/
  cli.py            # click CLI: index, serve, doctor, distill, bench, install-hooks
  config.py         # Settings + .claude-repo-mem/ state-dir resolution
  server.py         # MCP server: tool registry + server instructions
  tools/            # one module per MCP tool (recall, trace, expand, ...)
  indexer/          # walker, parsers/, synthesizers/, orchestrator, incremental
  retrieval/        # recall, trace, ranker, fill
  db/               # connection (sqlite-vec), schema, repository
  embeddings/       # bge_small (default), openai, voyage, factory
  llm/              # mcp_sampling (default), anthropic_api, factory
  summarizer/       # T2 summary backfill
  distill/          # extract durable memories from transcripts
  handoff/          # task snapshot + resume
  memory/           # durable memory writer
  queue/            # debounced background work queue (watcher)
  observability/    # tool-call counters
  bench/            # recall benchmark runner
tests/              # unit/, integration/, conftest.py
docs/               # tools.md, architecture.md, usage.md + specs/, plans/
```

When adding a new MCP tool, add a module under `tools/` exposing `tool_schema()`
and `handle(...)`, then register it in `server.py`.

## Conventions

- Modules are small and single-purpose; keep tool handlers thin and push logic
  into the matching subsystem (`retrieval/`, `memory/`, `handoff/`, etc.).
- `from __future__ import annotations` at the top of modules; type-annotate
  public functions.
- Tool descriptions in `tools/*.py` are user-facing — they steer how Claude Code
  calls the tool, so keep them accurate and action-oriented.

## Release flow

Releases follow the pattern visible in the git history:

1. Update [`CHANGELOG.md`](CHANGELOG.md) with the new version's notes.
2. Bump the `version` in `pyproject.toml`; commit as `bump: version X.Y.Z`.
3. Build and publish:
   ```bash
   python -m build          # sdist + wheel into dist/
   twine upload dist/*
   ```

`build` and `twine` are included in the `dev` extra.

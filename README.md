# claude-repo-mem

> Durable, hierarchical, repo-scoped memory for Claude Code. Local-first MCP server.

`claude-repo-mem` indexes your repository — code, docs, and your own accumulated decisions — into a SQLite database with hybrid lexical + vector retrieval, then exposes it to Claude Code as 11 MCP tools.

---

## Install

```bash
pip install claude-repo-mem
```

Requires Python 3.11+. Development install:

```bash
git clone https://github.com/amritmalla/claude-repo-mem
cd claude-repo-mem
pip install -e ".[dev]"
```

---

## Quick start

```bash
cd your-repo
claude-repo-mem index               # build the index (downloads bge-small on first run, ~90MB)
claude-repo-mem doctor              # verify: units, by_layer, T2 coverage, counters
```

To expose it to Claude Code, drop a `.mcp.json` in your repo root:

```json
{
  "mcpServers": {
    "claude-repo-mem": {
      "command": "claude-repo-mem",
      "args": ["serve", "--watch"]
    }
  }
}
```

Claude Code will auto-launch the server on workspace load. The `--watch` flag runs an incremental file watcher (debounced 750ms) so the index stays current as you edit.

Prefer not to run the watcher? Install a git hook instead:

```bash
claude-repo-mem install-hooks       # writes .git/hooks/post-commit
```

---

## CLI

```text
claude-repo-mem index [--embedder NAME] [--no-embed] [--reset]
claude-repo-mem serve [--watch | --no-watch]
claude-repo-mem doctor                              # layer counts, T2 coverage, counters
claude-repo-mem install-hooks [--force]             # git post-commit reindex
claude-repo-mem distill [--yes] [--transcript PATH] # extract durable memories from a transcript
claude-repo-mem bench   --fixture queries.yaml [--k 5] [--no-embed]
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

MIT. See [`LICENSE`](LICENSE).

Release notes for each version live in [`CHANGELOG.md`](CHANGELOG.md).

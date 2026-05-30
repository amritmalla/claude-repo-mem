# claude-repo-mem

> Durable, hierarchical, repo-scoped memory for Claude Code. Local-first MCP server.

`claude-repo-mem` indexes your repository — code, docs, and your own accumulated decisions — into a SQLite database with hybrid lexical + vector retrieval, then exposes it to Claude Code as 11 MCP tools.

---

## Why claude-repo-mem

Working with an AI agent in a real codebase runs into the same friction every session:

- **Context burns fast.** Native `Read`/`Grep` pull whole files into the window to answer narrow questions. `recall` returns ranked, summarized, scoped results inside a token budget — full source for the top hits, summaries for the rest — so you spend context on what matters.
- **Following code flow is expensive.** Chasing a caller → handler → route by hand means repeated reads. `trace` walks the relation graph from a seed and returns the connected source in one round-trip.
- **Nothing carries across sessions.** Decisions, conventions, and the "why" behind the code evaporate when the conversation ends. `remember`, `handoff`, and `resume` persist durable memory and task state as git-trackable markdown.
- **It stays on your machine.** Everything lives in a single `.claude-repo-mem/` directory with a local embedding model by default — no code leaves the repo, no API key required.

The result: the agent treats your repo as the authoritative source for its own structure and history, instead of rediscovering it file-by-file each time.

---

## Install

```bash
pip install claude-repo-mem
```

Requires Python 3.11+.

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
      "args": ["serve", "--watch", "--root", "/absolute/path/to/your-repo"]
    }
  }
}
```

Claude Code will auto-launch the server on workspace load. The `--watch` flag runs an incremental file watcher (debounced 750ms) so the index stays current as you edit.

> Set `--root` to your repo's absolute path. Claude Code launches MCP servers from a system working directory (not your repo), so without `--root` the server's auto-discovery can't find the index and recall comes back empty. See [docs/usage.md](docs/usage.md#wire-into-claude-code).

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

## Documentation

Full documentation lives in [`docs/`](docs/):

- [Usage guide](docs/usage.md) — indexing, Claude Code setup, configuration, workflows, troubleshooting.
- [Tool reference](docs/tools.md) — the 11 MCP tools, their parameters and returns.
- [Architecture](docs/architecture.md) — how indexing, storage, and retrieval work.
- [Contributing](CONTRIBUTING.md) — dev setup, tests, and release flow.

---

## License

MIT. See [`LICENSE`](LICENSE).

Release notes for each version live in [`CHANGELOG.md`](CHANGELOG.md).

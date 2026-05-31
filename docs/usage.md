# Usage guide

A task-oriented guide to running `claude-repo-mem` and wiring it into Claude Code.
For the tool API see [tools.md](tools.md); for internals see
[architecture.md](architecture.md).

## Install

```bash
pip install claude-repo-mem
```

Requires Python 3.11+.

## First index

From your repo root:

```bash
cd your-repo
claude-repo-mem index      # build the index (downloads bge-small on first run, ~90MB)
claude-repo-mem doctor      # verify: units, by_layer, T2 coverage, counters
```

`index` creates the `.claude-repo-mem/` state directory and populates the SQLite
index. The first run downloads the local embedding model (`bge-small`, ~90MB);
later runs reuse it.

`doctor` is your health check — it prints the repo root it resolved, the database
path, unit and relation counts, the per-layer breakdown, T2 (summary) coverage,
and tool-call counters.

### Useful `index` flags

| Flag | Effect |
|------|--------|
| `--reset` | Rebuild from scratch, discarding the existing index. |
| `--no-embed` | Index lexical/structure only, skip embeddings (faster; FTS-only recall). |
| `--embedder NAME` | Pick the embedding backend for this run. |
| `--root DIR` | Index a repo other than the current directory. |

## `init` — one-step setup

`claude-repo-mem init` is the recommended way to get started. It does two things in
a single command:

1. **Scaffolds the state directory.** Creates `.claude-repo-mem/` in the repo root
   (or the path given by `--root`).
2. **Writes or merges `.mcp.json`.** Adds a `claude-repo-mem` entry with the correct
   `--root` baked in. If an `.mcp.json` already exists, the merge preserves every
   other `mcpServers` entry; it refuses to overwrite a `claude-repo-mem` entry that
   already exists and differs, unless you pass `--force`.

```bash
cd your-repo
claude-repo-mem init                # scaffold + write/merge .mcp.json
claude-repo-mem init --no-watch     # same, but serve args omit --watch
claude-repo-mem init --embedder openai  # bake a non-default embedder into the serve args
claude-repo-mem init --index        # also run the first index immediately
claude-repo-mem init --hooks        # also install the post-commit git hook
claude-repo-mem init --index --hooks --force  # full setup, overwrite any existing entry
```

**`--index` and `--hooks` are off by default** — they are opt-in so `init` stays
fast and non-destructive on repos that already have a partial setup.

### Writing to Claude Desktop (`--target desktop`)

Pass `--target desktop` to merge the entry into Claude Desktop's global config
instead of the project `.mcp.json`:

```bash
claude-repo-mem init --target desktop
claude-repo-mem init --target desktop --root ~/projects/myrepo --force
```

The target file is the Claude Desktop config for the current OS:

| Platform | Path |
|----------|------|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

The server is keyed by folder name (e.g. `claude-repo-mem-myrepo`) so multiple
repos coexist in a single config without colliding. The absolute path to the
`claude-repo-mem` executable is resolved at init time and baked into the entry, so
Desktop always finds the right binary.

After writing, **restart Claude Desktop** to load the new server — Desktop reads
its config only at startup.

### Multi-project usage

Run `init` once per repo. Each repo gets:

- Its own absolute `--root` baked into its own `.mcp.json`, so Claude Code launches a
  separate server instance per project.
- An isolated SQLite database under its own `.claude-repo-mem/`, so indexes never
  collide regardless of how many projects you have open simultaneously.

```bash
cd ~/projects/api      && claude-repo-mem init --index
cd ~/projects/frontend && claude-repo-mem init --index
```

Each project's `.mcp.json` carries a distinct `--root`, and the two servers run
independently.

## Wire into Claude Code

Drop a `.mcp.json` in your repo root and pin the repo with `--root`:

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

Claude Code auto-launches the server on workspace load. After editing `.mcp.json`,
reconnect the server (restart Claude Code, or use `/mcp` → reconnect).

> **Why an explicit root is required.** Claude Code launches MCP servers from a
> system working directory (e.g. `C:\Windows\System32` on Windows), *not* your repo,
> so cwd-based discovery can't find `.claude-repo-mem/`. Current Claude Code builds
> do **not** inject `CLAUDE_PROJECT_DIR` into the spawned server's environment, nor
> advertise the MCP `roots` capability — so the server has no way to learn the repo
> on its own. Pin it explicitly.

### Root resolution order

The server resolves the repo root in this order:

1. **`--root` flag** (passed in `args`) — when present, used directly.
2. **`CLAUDE_REPO_MEM_ROOT`** — explicit override (env var or `.mcp.json` `env`).
3. **Walk up from the working directory** looking for `.claude-repo-mem/`.
4. **`CLAUDE_PROJECT_DIR`** — used if the host injects it (future Claude Code builds
   or other MCP hosts may; current builds do not).

Equivalent to `--root`, you can use the `CLAUDE_REPO_MEM_ROOT` environment variable
(handy under hosts that only expose `env`, and it accepts `.mcp.json` variable
expansion):

```json
"env": { "CLAUDE_REPO_MEM_ROOT": "/absolute/path/to/your-repo" }
```

The `--watch` flag runs an incremental file watcher (debounced 750ms) so the index
stays current as you edit. Prefer not to run a watcher? Install a git hook instead:

```bash
claude-repo-mem install-hooks      # writes .git/hooks/post-commit
```

## Configuration

State and backends are configured by environment variables (read at server/CLI
launch).

### Embedding backend

Selected by `CLAUDE_REPO_MEM_EMBEDDER` (or the `--embedder` flag on `index`):

| Value | Model | Requirement |
|-------|-------|-------------|
| `bge-small` (default) | `BAAI/bge-small-en-v1.5`, 384-dim, local CPU | none |
| `openai` | OpenAI embeddings | `OPENAI_API_KEY` |
| `voyage` | Voyage, 512-dim | `VOYAGE_API_KEY` |

> Changing the embedder changes the vector space. Re-index with `--reset` after
> switching backends.

### LLM backend

Summarization (T2) and `plan_task` need an LLM, selected by `CLAUDE_REPO_MEM_LLM`:

| Value | Backend | Requirement |
|-------|---------|-------------|
| `mcp` (default) | MCP host sampling (Claude Code does the inference) | runs inside an MCP session |
| `anthropic` | Direct Anthropic API | `ANTHROPIC_API_KEY` |

With the default `mcp` backend there is no API key and no extra cost — the host
model performs summarization. Use `anthropic` when running the CLI outside an MCP
session (e.g. summarizing during a plain `index` run).

### Scopes

Scopes partition memory and let you filter recall (`scopes: ["backend/auth"]`).
Scope configuration lives in `.claude-repo-mem/scopes.yml`; list active scopes and
their unit counts with the `scopes` tool.

## Workflows

### Distill memories from a transcript

Extract durable memories (decisions, conventions, preferences) from a Claude
session transcript:

```bash
claude-repo-mem distill --transcript path/to/transcript.jsonl
claude-repo-mem distill --transcript path/to/transcript.jsonl --yes   # accept all proposals
```

Without `--yes` you confirm each proposed memory interactively. Accepted memories
are written under `.claude-repo-mem/memory/` and become recallable. With no
`--transcript`, distill operates on the most recent transcript it can find.

### Handoff and resume across sessions

For long or multi-part work, snapshot a task at the end of a session and pick it
up later — via the `handoff` and `resume` tools (see [tools.md](tools.md#handoff)).
Snapshots are markdown under `.claude-repo-mem/handoffs/` and are git-trackable.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Recall returns nothing; server seems to look in `C:\Windows\System32` or another system dir | Host (e.g. a non-Claude-Code MCP client) launched the server from its working directory and did not set `CLAUDE_PROJECT_DIR` | Pin the repo: add `"--root", "/abs/path/to/repo"` to `.mcp.json` args (or set `CLAUDE_REPO_MEM_ROOT`) and reconnect. Verify with `claude-repo-mem doctor --root /abs/path`. |
| Empty or stale results after big changes | Index out of date | Re-run `claude-repo-mem index` (or `--reset`), or enable `--watch` / `install-hooks`. |
| Long pause on first `index` | One-time `bge-small` model download (~90MB) | Wait for the first run; subsequent runs are fast. |
| `doctor` shows low `t2_coverage` right after indexing | Summaries backfill asynchronously and need an LLM backend | Let summarization catch up; ensure an LLM backend is configured. |
| `OPENAI_API_KEY not set` / `VOYAGE_API_KEY not set` | Selected a remote embedder without its key | Set the key, or switch back to `bge-small`. |

## CLI summary

```text
claude-repo-mem init  [--root PATH] [--embedder NAME] [--no-watch] [--index] [--hooks] [--force] [--target claude-code|desktop]
claude-repo-mem index [--embedder NAME] [--no-embed] [--reset] [--root DIR]
claude-repo-mem serve [--watch | --no-watch] [--root DIR]
claude-repo-mem doctor [--root DIR]                  # layer counts, T2 coverage, counters
claude-repo-mem install-hooks [--force] [--root DIR] # git post-commit reindex
claude-repo-mem distill [--yes] [--transcript PATH] [--root DIR]
claude-repo-mem bench --fixture queries.yaml [--k 5] [--no-embed] [--root DIR]
```

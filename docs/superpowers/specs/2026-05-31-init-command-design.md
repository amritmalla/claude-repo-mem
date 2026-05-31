# Design: `claude-repo-mem init`

**Date:** 2026-05-31
**Status:** Approved (design); pending implementation plan

## Purpose

A single `init` command that makes a repository ready for Claude Code in one run:
scaffolds `.claude-repo-mem/`, merges a correct `claude-repo-mem` entry into the
repo's `.mcp.json` (with embedder/watch flags baked into the `serve` args),
optionally builds the first index and installs the git hook, then prints next
steps.

This also fulfills the two existing *"run `claude-repo-mem init` first"* error
tips that already reference an unbuilt command:

- `src/claude_repo_mem/config.py:49`
- `src/claude_repo_mem/cli.py:193`

## Decisions (from brainstorming)

- **Storage model:** in-repo only — always `<repo>/.claude-repo-mem/`. No changes
  to `Settings` discovery logic.
- **`.mcp.json` handling:** merge — preserve other MCP servers, add/update only
  the `claude-repo-mem` entry.
- **Scope:** scaffold dir + merge `.mcp.json` always; first index and git hook
  behind flags; next steps always printed.
- **Other config (embedder, watch):** baked into the `serve` args inside
  `.mcp.json`. No new config file. Env vars still override at runtime.

## Command surface

```text
claude-repo-mem init [--root PATH]      # defaults to cwd
                     [--embedder NAME]   # bge-small|openai|voyage; baked into .mcp.json
                     [--no-watch]        # default: watch on (baked into .mcp.json)
                     [--index]           # run first index now (default off)
                     [--hooks]           # install post-commit hook (default off)
                     [--force]           # overwrite our own .mcp.json entry without prompt
```

## What it writes

### State dir

Reuses `Settings.for_repo(root)`, which already creates `.claude-repo-mem/`
(`config.py:54-57`). No new path logic.

### `.mcp.json` (merge semantics)

A new module `mcp_config.py` (kept out of `cli.py` so it is unit-testable in
isolation):

- Reads `<root>/.mcp.json` if present; parses JSON. On malformed JSON, refuse and
  surface the parse error — do not write.
- Ensures the `mcpServers` object exists; preserves every other server untouched.
- Sets `mcpServers["claude-repo-mem"]` to:

  ```json
  {
    "command": "claude-repo-mem",
    "args": ["serve", "--watch", "--root", "<absolute root>", "--embedder", "<name>"]
  }
  ```

  - `--watch` omitted (and `--no-watch` added) when `--no-watch` is passed.
  - `--embedder` omitted when the default (`bge-small`) is in effect, to keep the
    args clean.
- If a `claude-repo-mem` entry already exists **and differs**, require `--force`
  (or prompt) before replacing, so a user's hand-tuned args are never silently
  clobbered. Other servers are never gated.
- Writes back with stable 2-space indentation.

## Optional steps & output

- `--index`: uses the same path as the `index` command (`make_embedder` +
  `init_db` + `full_reindex`). Heavy/slow, so off by default.
- `--hooks`: the existing `install-hooks` body is extracted into a shared function
  so both `init` and `install-hooks` call it (no duplication); `--force` passes
  through.
- Always: print a short next-steps block — whether the index was built or still
  needs running, and "restart Claude Code (or reload the workspace) to pick up the
  MCP server."

## Error handling

- Non-directory / unwritable root → clear `ClickException`.
- Malformed existing `.mcp.json` → refuse, show parse error, do not write.
- `--hooks` outside a git repo → same message `install-hooks` already gives.
- Embedder download failures only possible under `--index`; surface the
  underlying error.

## Testing

**`mcp_config.py` merge unit tests:**
- Fresh file (none exists).
- Existing file with other servers — other servers preserved.
- Existing `claude-repo-mem` entry — replacement gated on `--force`.
- Malformed file — rejected, not written.
- Flag → args mapping (`--no-watch`, `--embedder`, default omission).

**`init` command via click `CliRunner` in a tmp repo:**
- State dir created.
- `.mcp.json` correct.
- `--hooks` writes the post-commit hook.
- Next-steps printed.
- `--index` covered by a light/fast path (avoid model download in CI).

## Multi-project

No special handling required. State is in-repo and each `.mcp.json` carries an
absolute `--root`, so running `init` in repo A and repo B produces two isolated
setups that Claude Code launches as separate server processes against separate
SQLite databases. `init` simply makes that per-repo setup a one-liner.

## Out of scope

- Custom / out-of-repo storage locations.
- A separate config file (`config.toml`).
- Changes to `Settings.discover()`.

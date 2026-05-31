# `claude-repo-mem init` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `claude-repo-mem init` command that scaffolds `.claude-repo-mem/`, merges a correct `claude-repo-mem` entry into the repo's `.mcp.json`, and optionally runs the first index and installs the git hook.

**Architecture:** A new pure, unit-testable `mcp_config.py` module owns `.mcp.json` read/merge/write. The git-hook body is extracted from the existing `install-hooks` command into a shared helper so `init` reuses it. A new `init` click command in `cli.py` orchestrates: `Settings.for_repo` (scaffold dir) → `merge_mcp_config` → optional `--index`/`--hooks` → printed next steps.

**Tech Stack:** Python 3.11+, `click`, `pytest`, `click.testing.CliRunner`. JSON via stdlib `json`.

---

## File Structure

- Create: `src/claude_repo_mem/mcp_config.py` — `.mcp.json` merge logic + errors. One responsibility: managing the MCP config file.
- Modify: `src/claude_repo_mem/cli.py` — extract `_write_post_commit_hook` helper; refactor `install_hooks` to use it; add `init` command.
- Create: `tests/unit/test_mcp_config.py` — merge unit tests.
- Create: `tests/unit/test_cli_init.py` — `init` command tests via `CliRunner`.

---

## Task 1: Extract the git-hook writer into a shared helper

Refactor only — no behavior change. Existing `tests/unit/test_cli_install_hooks.py` must stay green.

**Files:**
- Modify: `src/claude_repo_mem/cli.py:108-134`
- Test: `tests/unit/test_cli_install_hooks.py` (existing, unchanged)

- [ ] **Step 1: Add the shared helper and refactor `install_hooks`**

In `src/claude_repo_mem/cli.py`, add this helper above the `install_hooks` command:

```python
def _write_post_commit_hook(repo_root: Path, force: bool) -> Path:
    """Write a post-commit hook that reindexes. Returns the hook path.

    Raises click.ClickException if not a git repo or the hook exists
    without --force.
    """
    git_dir = repo_root / ".git"
    if not git_dir.is_dir():
        raise click.ClickException(f"not a git repo: {repo_root}")
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "post-commit"
    if hook_path.exists() and not force:
        raise click.ClickException(
            f"{hook_path} already exists; rerun with --force to overwrite"
        )
    hook_path.write_text(
        "#!/bin/sh\n"
        "# Installed by claude-repo-mem install-hooks\n"
        "claude-repo-mem index --no-embed >/dev/null 2>&1 || true\n",
        encoding="utf-8",
    )
    try:
        hook_path.chmod(0o755)
    except Exception:
        pass  # Windows
    return hook_path
```

Then replace the body of `install_hooks` (the lines after the docstring) with:

```python
    repo_root = root or Path.cwd()
    hook_path = _write_post_commit_hook(repo_root, force)
    click.echo(f"installed: {hook_path}")
```

- [ ] **Step 2: Run the existing hook tests to verify no regression**

Run: `python -m pytest tests/unit/test_cli_install_hooks.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 3: Commit**

```bash
git add src/claude_repo_mem/cli.py
git commit -m "refactor: extract _write_post_commit_hook helper from install-hooks"
```

---

## Task 2: `mcp_config.py` — build server args

**Files:**
- Create: `src/claude_repo_mem/mcp_config.py`
- Test: `tests/unit/test_mcp_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_mcp_config.py`:

```python
from pathlib import Path

from claude_repo_mem.mcp_config import build_server_entry, DEFAULT_EMBEDDER


def test_build_server_entry_defaults():
    root = Path("/abs/repo")
    entry = build_server_entry(root, embedder=None, watch=True)
    assert entry["command"] == "claude-repo-mem"
    assert entry["args"] == ["serve", "--watch", "--root", str(root.resolve())]


def test_build_server_entry_no_watch():
    entry = build_server_entry(Path("/abs/repo"), embedder=None, watch=False)
    assert "--watch" not in entry["args"]
    assert "--no-watch" in entry["args"]


def test_build_server_entry_custom_embedder():
    entry = build_server_entry(Path("/abs/repo"), embedder="openai", watch=True)
    assert "--embedder" in entry["args"]
    assert entry["args"][entry["args"].index("--embedder") + 1] == "openai"


def test_build_server_entry_omits_default_embedder():
    entry = build_server_entry(Path("/abs/repo"), embedder=DEFAULT_EMBEDDER, watch=True)
    assert "--embedder" not in entry["args"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_mcp_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_repo_mem.mcp_config'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/claude_repo_mem/mcp_config.py`:

```python
from __future__ import annotations

from pathlib import Path

DEFAULT_EMBEDDER = "bge-small"
SERVER_KEY = "claude-repo-mem"


def build_server_entry(repo_root: Path, embedder: str | None, watch: bool) -> dict:
    """Build the .mcp.json entry for the claude-repo-mem server."""
    args = ["serve"]
    if watch:
        args.append("--watch")
    else:
        args.append("--no-watch")
    args += ["--root", str(repo_root.resolve())]
    if embedder and embedder != DEFAULT_EMBEDDER:
        args += ["--embedder", embedder]
    return {"command": "claude-repo-mem", "args": args}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_mcp_config.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/claude_repo_mem/mcp_config.py tests/unit/test_mcp_config.py
git commit -m "feat: add build_server_entry for .mcp.json"
```

---

## Task 3: `mcp_config.py` — merge into `.mcp.json`

**Files:**
- Modify: `src/claude_repo_mem/mcp_config.py`
- Test: `tests/unit/test_mcp_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_mcp_config.py`:

```python
import json
import pytest

from claude_repo_mem.mcp_config import merge_mcp_config, McpConfigError


def test_merge_creates_file_when_absent(tmp_path: Path):
    action = merge_mcp_config(tmp_path, embedder=None, watch=True, force=False)
    assert action == "created"
    data = json.loads((tmp_path / ".mcp.json").read_text())
    assert "claude-repo-mem" in data["mcpServers"]


def test_merge_preserves_other_servers(tmp_path: Path):
    (tmp_path / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"other": {"command": "x", "args": []}}
    }))
    merge_mcp_config(tmp_path, embedder=None, watch=True, force=False)
    data = json.loads((tmp_path / ".mcp.json").read_text())
    assert "other" in data["mcpServers"]
    assert "claude-repo-mem" in data["mcpServers"]


def test_merge_unchanged_when_entry_identical(tmp_path: Path):
    merge_mcp_config(tmp_path, embedder=None, watch=True, force=False)
    action = merge_mcp_config(tmp_path, embedder=None, watch=True, force=False)
    assert action == "unchanged"


def test_merge_conflict_without_force(tmp_path: Path):
    (tmp_path / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"claude-repo-mem": {"command": "claude-repo-mem", "args": ["custom"]}}
    }))
    with pytest.raises(McpConfigError):
        merge_mcp_config(tmp_path, embedder=None, watch=True, force=False)


def test_merge_force_replaces_conflicting_entry(tmp_path: Path):
    (tmp_path / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"claude-repo-mem": {"command": "claude-repo-mem", "args": ["custom"]}}
    }))
    action = merge_mcp_config(tmp_path, embedder=None, watch=True, force=True)
    assert action == "updated"
    data = json.loads((tmp_path / ".mcp.json").read_text())
    assert data["mcpServers"]["claude-repo-mem"]["args"] != ["custom"]


def test_merge_rejects_malformed_json(tmp_path: Path):
    (tmp_path / ".mcp.json").write_text("{not valid json")
    with pytest.raises(McpConfigError):
        merge_mcp_config(tmp_path, embedder=None, watch=True, force=False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_mcp_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'merge_mcp_config'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/claude_repo_mem/mcp_config.py`:

```python
import json


class McpConfigError(Exception):
    """Raised when .mcp.json cannot be safely merged."""


def merge_mcp_config(
    repo_root: Path, embedder: str | None, watch: bool, force: bool
) -> str:
    """Merge the claude-repo-mem entry into <repo_root>/.mcp.json.

    Returns "created", "updated", or "unchanged". Other servers are
    preserved. Raises McpConfigError on malformed JSON or on a differing
    existing entry without force.
    """
    path = repo_root / ".mcp.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise McpConfigError(f"{path} is not valid JSON: {e}") from e
        if not isinstance(data, dict):
            raise McpConfigError(f"{path} must contain a JSON object")
        created = False
    else:
        data = {}
        created = True

    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise McpConfigError(f"{path}: 'mcpServers' must be an object")

    new_entry = build_server_entry(repo_root, embedder, watch)
    existing = servers.get(SERVER_KEY)
    if existing == new_entry:
        return "unchanged"
    if existing is not None and not force:
        raise McpConfigError(
            f"{path} already has a '{SERVER_KEY}' entry that differs; "
            "rerun with --force to overwrite it"
        )

    servers[SERVER_KEY] = new_entry
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return "created" if created else "updated"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_mcp_config.py -v`
Expected: PASS (10 tests total).

- [ ] **Step 5: Commit**

```bash
git add src/claude_repo_mem/mcp_config.py tests/unit/test_mcp_config.py
git commit -m "feat: add merge_mcp_config with preserve/force/malformed handling"
```

---

## Task 4: The `init` command

**Files:**
- Modify: `src/claude_repo_mem/cli.py`
- Test: `tests/unit/test_cli_init.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_cli_init.py`:

```python
import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from claude_repo_mem.cli import main


def test_init_scaffolds_dir_and_mcp_json(tmp_path: Path):
    runner = CliRunner()
    res = runner.invoke(main, ["init", "--root", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert (tmp_path / ".claude-repo-mem").is_dir()
    data = json.loads((tmp_path / ".mcp.json").read_text())
    assert "claude-repo-mem" in data["mcpServers"]
    args = data["mcpServers"]["claude-repo-mem"]["args"]
    assert "--root" in args


def test_init_prints_next_steps(tmp_path: Path):
    runner = CliRunner()
    res = runner.invoke(main, ["init", "--root", str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert "claude-repo-mem index" in res.output


def test_init_with_hooks_writes_hook(tmp_path: Path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    runner = CliRunner()
    res = runner.invoke(main, ["init", "--root", str(tmp_path), "--hooks"])
    assert res.exit_code == 0, res.output
    hook = tmp_path / ".git" / "hooks" / "post-commit"
    assert hook.exists()


def test_init_conflict_requires_force(tmp_path: Path):
    (tmp_path / ".mcp.json").write_text(json.dumps({
        "mcpServers": {"claude-repo-mem": {"command": "claude-repo-mem", "args": ["custom"]}}
    }))
    runner = CliRunner()
    res = runner.invoke(main, ["init", "--root", str(tmp_path)])
    assert res.exit_code != 0
    assert "force" in res.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_cli_init.py -v`
Expected: FAIL — `init` is not a registered command (`res.exit_code != 0` with "No such command 'init'").

- [ ] **Step 3: Write minimal implementation**

Add the `init` command to `src/claude_repo_mem/cli.py` (after the `serve` command, before the `if __name__` guard). The `from .config import Settings` import already exists at the top of the file:

```python
@main.command()
@click.option("--root", type=click.Path(file_okay=False, path_type=Path),
              default=None, help="Repo root (defaults to cwd)")
@click.option("--embedder", type=str, default=None,
              help="Embedder baked into .mcp.json (bge-small|openai|voyage)")
@click.option("--no-watch", is_flag=True, default=False,
              help="Bake --no-watch into .mcp.json (default: watch on)")
@click.option("--index", "do_index", is_flag=True, default=False,
              help="Run the first index now (downloads bge-small on first run)")
@click.option("--hooks", is_flag=True, default=False,
              help="Install the post-commit reindex git hook")
@click.option("--force", is_flag=True, default=False,
              help="Overwrite an existing claude-repo-mem .mcp.json entry / git hook")
def init(root: Path | None, embedder: str | None, no_watch: bool,
         do_index: bool, hooks: bool, force: bool) -> None:
    """Initialize a repo: scaffold .claude-repo-mem/ and wire up .mcp.json."""
    from .mcp_config import merge_mcp_config, McpConfigError

    repo_root = (root or Path.cwd()).resolve()
    settings = Settings.for_repo(repo_root)  # creates .claude-repo-mem/

    try:
        action = merge_mcp_config(
            repo_root, embedder=embedder, watch=not no_watch, force=force
        )
    except McpConfigError as e:
        raise click.ClickException(str(e))
    click.echo(f".mcp.json: {action}")

    if hooks:
        hook_path = _write_post_commit_hook(repo_root, force)
        click.echo(f"hook: {hook_path}")

    indexed = False
    if do_index:
        from .embeddings.factory import make_embedder
        emb = make_embedder(embedder)
        init_db(settings.db_path, dim=emb.dim)
        stats = full_reindex(settings, embedder=emb)
        click.echo(f"indexed: units_written={stats['units_written']}")
        indexed = True

    click.echo("\nNext steps:")
    if not indexed:
        click.echo("  - run `claude-repo-mem index` to build the index")
    click.echo("  - restart Claude Code (or reload the workspace) to load the MCP server")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/test_cli_init.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full unit suite to confirm no regressions**

Run: `python -m pytest tests/unit -q`
Expected: PASS (no failures).

- [ ] **Step 6: Commit**

```bash
git add src/claude_repo_mem/cli.py tests/unit/test_cli_init.py
git commit -m "feat: add init command to scaffold repo and wire up .mcp.json"
```

---

## Task 5: Documentation

**Files:**
- Modify: `README.md` (the `## CLI` block, ~line 67)
- Modify: `docs/usage.md` (the Claude Code wiring section)

- [ ] **Step 1: Add `init` to the README CLI list**

In `README.md`, add this line at the top of the CLI code block (currently starting at line 68):

```text
claude-repo-mem init [--root PATH] [--embedder NAME] [--no-watch] [--index] [--hooks] [--force]
```

Replace the surrounding quick-start prose so it suggests `claude-repo-mem init` as the one-step setup (creates `.claude-repo-mem/` and `.mcp.json`), with manual `.mcp.json` editing as the alternative.

- [ ] **Step 2: Add an `init` subsection to docs/usage.md**

In `docs/usage.md`, near the "wire into Claude Code" section, add a short subsection documenting `claude-repo-mem init`: that it scaffolds the state dir, merges `.mcp.json` (preserving other servers), and that `--index`/`--hooks` are opt-in. Note multi-project: run it once per repo; each gets its own absolute `--root` and isolated database.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/usage.md
git commit -m "docs: document the init command"
```

---

## Self-Review Notes

- **Spec coverage:** command surface (Task 4), in-repo scaffold via `Settings.for_repo` (Task 4), merge semantics + `--force` + malformed handling (Task 3), flag→args mapping incl. default-embedder omission (Task 2), `--index`/`--hooks`/next-steps (Task 4), shared hook helper to avoid duplication (Task 1), tests (Tasks 2-4), docs incl. multi-project note (Task 5). All spec sections mapped.
- **Type consistency:** `build_server_entry`, `merge_mcp_config`, `McpConfigError`, `_write_post_commit_hook`, `SERVER_KEY`, `DEFAULT_EMBEDDER` used consistently across tasks.
- **No placeholders:** every code/test step shows full content.

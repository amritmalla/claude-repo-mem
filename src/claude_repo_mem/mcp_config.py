from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

DEFAULT_EMBEDDER = "bge-small"
SERVER_KEY = "claude-repo-mem"


def build_server_entry(
    repo_root: Path,
    embedder: str | None,
    watch: bool,
    command: str = "claude-repo-mem",
) -> dict:
    """Build the .mcp.json entry for the claude-repo-mem server."""
    args = ["serve"]
    if watch:
        args.append("--watch")
    else:
        args.append("--no-watch")
    args += ["--root", str(repo_root.resolve())]
    if embedder and embedder != DEFAULT_EMBEDDER:
        args += ["--embedder", embedder]
    return {"command": command, "args": args}


class McpConfigError(Exception):
    """Raised when .mcp.json cannot be safely merged."""


def _merge_server_into(config_path: Path, server_key: str, entry: dict, force: bool) -> str:
    """Merge `entry` under `server_key` into the mcpServers map of config_path.

    Returns 'created' | 'updated' | 'unchanged'. Preserves other servers.
    Reads with utf-8-sig so a BOM-prefixed file is accepted. Raises McpConfigError
    on malformed JSON / non-object structures / a differing existing entry without force.
    """
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as e:
            raise McpConfigError(f"{config_path} is not valid JSON: {e}") from e
        if not isinstance(data, dict):
            raise McpConfigError(f"{config_path} must contain a JSON object")
        created = False
    else:
        data = {}
        created = True

    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise McpConfigError(f"{config_path}: 'mcpServers' must be an object")

    existing = servers.get(server_key)
    if existing == entry:
        return "unchanged"
    if existing is not None and not force:
        raise McpConfigError(
            f"{config_path} already has a '{server_key}' entry that differs; "
            "rerun with --force to overwrite it"
        )

    servers[server_key] = entry
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return "created" if created else "updated"


def merge_mcp_config(
    repo_root: Path, embedder: str | None, watch: bool, force: bool
) -> str:
    """Merge the claude-repo-mem entry into <repo_root>/.mcp.json.

    Returns "created", "updated", or "unchanged". Other servers are
    preserved. Raises McpConfigError on malformed JSON or on a differing
    existing entry without force.
    """
    path = repo_root / ".mcp.json"
    entry = build_server_entry(repo_root, embedder, watch)
    return _merge_server_into(path, SERVER_KEY, entry, force)


def desktop_config_path() -> Path:
    """Path to Claude Desktop's global config file for the current OS."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def merge_desktop_config(
    repo_root: Path, embedder: str | None, watch: bool, force: bool
) -> tuple[str, Path]:
    """Merge a claude-repo-mem entry into Claude Desktop's global config.

    Keys the server by folder name so multiple repos coexist. Resolves the
    absolute claude-repo-mem executable path (falls back to the bare name).
    Returns (action, config_path).
    """
    repo_root = repo_root.resolve()
    command = shutil.which("claude-repo-mem") or "claude-repo-mem"
    entry = build_server_entry(repo_root, embedder, watch, command=command)
    key = f"claude-repo-mem-{repo_root.name}"
    cfg = desktop_config_path()
    action = _merge_server_into(cfg, key, entry, force)
    return action, cfg

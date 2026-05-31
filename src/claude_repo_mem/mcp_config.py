from __future__ import annotations

import json
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

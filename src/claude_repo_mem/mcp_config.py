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

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

STATE_DIRNAME = ".claude-repo-mem"


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    state_dir: Path
    db_path: Path
    blobs_dir: Path
    handoffs_dir: Path
    memory_dir: Path
    scopes_yml: Path
    embedder: str

    @classmethod
    def discover(cls, start: Path | None = None) -> "Settings":
        # 1. Explicit override always wins.
        explicit = os.environ.get("CLAUDE_REPO_MEM_ROOT")
        if explicit:
            root = Path(explicit).resolve()
            if (root / STATE_DIRNAME).is_dir():
                return cls._build(root)

        # 2. Walk up from the working directory.
        cwd = (start or Path.cwd()).resolve()
        for candidate in [cwd, *cwd.parents]:
            if (candidate / STATE_DIRNAME).is_dir():
                return cls._build(candidate)

        # 3. Fall back to the project root Claude Code injects into the
        #    spawned MCP server's environment. This handles the common case
        #    where the host launches the server from a system directory
        #    (e.g. C:\Windows\System32) rather than the repo.
        project = os.environ.get("CLAUDE_PROJECT_DIR")
        if project:
            root = Path(project).resolve()
            if (root / STATE_DIRNAME).is_dir():
                return cls._build(root)

        raise FileNotFoundError(
            f"No {STATE_DIRNAME}/ directory found in {cwd} or any parent "
            "(and neither CLAUDE_REPO_MEM_ROOT nor CLAUDE_PROJECT_DIR points "
            "to an initialized repo). Run `claude-repo-mem init` first, or pass "
            "--root <repo-path>."
        )

    @classmethod
    def for_repo(cls, repo_root: Path) -> "Settings":
        repo_root = repo_root.resolve()
        (repo_root / STATE_DIRNAME).mkdir(exist_ok=True)
        return cls._build(repo_root)

    @classmethod
    def _build(cls, repo_root: Path) -> "Settings":
        state = repo_root / STATE_DIRNAME
        return cls(
            repo_root=repo_root,
            state_dir=state,
            db_path=state / "db.sqlite",
            blobs_dir=state / "blobs",
            handoffs_dir=state / "handoffs",
            memory_dir=state / "memory",
            scopes_yml=state / "scopes.yml",
            embedder=os.environ.get("CLAUDE_REPO_MEM_EMBED", "bge-small"),
        )

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
        cwd = (start or Path.cwd()).resolve()
        for candidate in [cwd, *cwd.parents]:
            if (candidate / STATE_DIRNAME).is_dir():
                return cls._build(candidate)
        raise FileNotFoundError(
            f"No {STATE_DIRNAME}/ directory found in {cwd} or any parent. "
            "Run `claude-repo-mem init` first."
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

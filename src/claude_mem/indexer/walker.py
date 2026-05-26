from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterator

SUPPORTED_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".md", ".markdown"}
SKIP_DIRS = {
    ".git", ".hg", ".svn",
    ".claude-mem",
    "node_modules", ".venv", "venv", "env",
    "__pycache__", ".pytest_cache",
    "dist", "build", ".next", ".turbo",
    ".tox", ".mypy_cache", ".ruff_cache",
}


def walk_repo(root: Path) -> Iterator[Path]:
    """Yield absolute paths to indexable files under `root`."""
    root = root.resolve()
    for path in _walk(root):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS:
            yield path


def _walk(dirpath: Path) -> Iterator[Path]:
    try:
        entries = list(dirpath.iterdir())
    except (PermissionError, OSError):
        return
    for entry in entries:
        if entry.is_dir():
            if entry.name == ".claude-mem":
                mem = entry / "memory"
                if mem.is_dir():
                    yield from _walk(mem)
                continue
            if entry.name in SKIP_DIRS:
                continue
            yield from _walk(entry)
        else:
            yield entry


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def derive_scope(rel_path: Path) -> str:
    """Scope = parent directory of the file (POSIX-joined), or 'root' if at top."""
    parts = rel_path.parts[:-1]
    if not parts:
        return "root"
    return "/".join(parts)

from __future__ import annotations

import datetime as _dt
import hashlib
import re
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

import yaml

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository
from ..indexer.parsers.memory_md import FRONTMATTER_RE, MemoryMarkdownParser
from ..units.typed import KIND_VALID_FOR_LAYER
from .lifecycle import TOMBSTONE_HANDLE, ensure_tombstone_unit


@dataclass(frozen=True)
class MemoryWriteResult:
    handle: str
    slug: str
    path: Path


VALID_KINDS = KIND_VALID_FOR_LAYER["memory"]


def remember(
    settings: Settings,
    *,
    fact: str,
    scope: str,
    kind: str = "fact",
    confidence: Optional[float] = None,
    supersedes: Optional[str] = None,
) -> MemoryWriteResult:
    if kind not in VALID_KINDS:
        raise ValueError(f"invalid memory kind: {kind!r}")

    memory_root = settings.memory_dir.resolve()
    scope_dir = _scope_directory(memory_root, scope)

    slug = _slugify(fact)
    path = scope_dir / f"{slug}.md"
    _validate_memory_path(path, memory_root)

    if path.exists():
        h = hashlib.sha256(fact.encode("utf-8")).hexdigest()[:6]
        slug = f"{slug}-{h}"
        path = scope_dir / f"{slug}.md"
        _validate_memory_path(path, memory_root)

    scope_dir.mkdir(parents=True, exist_ok=True)

    frontmatter = {
        "kind": kind,
        "scope": scope,
        "created_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if confidence is not None:
        frontmatter["confidence"] = confidence
    if supersedes:
        frontmatter["supersedes"] = supersedes

    body = fact.strip()
    md = "---\n"
    for k, v in frontmatter.items():
        md += f"{k}: {v}\n"
    md += "---\n\n"
    md += body + "\n"
    path.write_text(md, encoding="utf-8")

    parsed = MemoryMarkdownParser().parse(path, md)
    [unit] = parsed.units
    with closing(connect(settings.db_path)) as conn:
        repo = Repository(conn)
        with repo.transaction():
            repo.upsert_unit(unit)
            if supersedes:
                old = repo.get_unit(supersedes)
                if old is not None:
                    repo.upsert_unit(replace(old, superseded_by=unit.id))

    return MemoryWriteResult(handle=unit.id, slug=slug, path=path)


def _scope_directory(memory_root: Path, scope: str) -> Path:
    parts = scope.split("/")
    if (
        any(part in {"", ".", ".."} or part.endswith((" ", ".")) for part in parts)
        or "\\" in scope
        or ":" in scope
        or any(ord(char) < 32 for char in scope)
    ):
        raise ValueError(
            "scope must be a relative '/'-separated path with no empty, '.', '..', "
            "or trailing-dot/space components, backslashes, colons, or control characters"
        )
    scope_dir = memory_root.joinpath(*parts)
    _validate_memory_path(scope_dir, memory_root)
    return scope_dir


def _validate_memory_path(path: Path, memory_root: Path) -> None:
    # Resolve directory links and file symlinks before making any changes.
    if not path.resolve().is_relative_to(memory_root):
        raise ValueError("scope and memory file must stay inside the memory directory")


def forget(settings: Settings, *, handle: str) -> None:
    with closing(connect(settings.db_path)) as conn:
        repo = Repository(conn)
        unit = repo.get_unit(handle)
        if unit is None:
            raise KeyError(handle)
        if unit.layer != "memory":
            raise ValueError(f"forget() only operates on memory units; got {unit.layer}")

        if unit.source_ref:
            path = Path(unit.source_ref)
            if path.exists():
                text = path.read_text(encoding="utf-8")
                match = FRONTMATTER_RE.match(text)
                front = (yaml.safe_load(match.group(1)) or {}) if match else {}
                body = text[match.end():] if match else text
                front["tombstoned"] = True
                text = "---\n" + yaml.safe_dump(front, sort_keys=False) + "---\n" + body
                path.write_text(text, encoding="utf-8")

        with repo.transaction():
            ensure_tombstone_unit(repo)
            repo.upsert_unit(replace(unit, superseded_by=TOMBSTONE_HANDLE))


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, max_chars: int = 40) -> str:
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return s[:max_chars] or "memory"

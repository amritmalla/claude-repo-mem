from __future__ import annotations

import datetime as _dt
import hashlib
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository
from ..indexer.parsers.memory_md import MemoryMarkdownParser
from ..units.typed import KIND_VALID_FOR_LAYER


@dataclass(frozen=True)
class MemoryWriteResult:
    handle: str
    slug: str
    path: Path


VALID_KINDS = KIND_VALID_FOR_LAYER["memory"]
TOMBSTONE_HANDLE = "tombstone://"


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

    scope_dir = settings.memory_dir.joinpath(*scope.split("/"))
    scope_dir.mkdir(parents=True, exist_ok=True)

    slug = _slugify(fact)
    path = scope_dir / f"{slug}.md"

    if path.exists():
        h = hashlib.sha256(fact.encode("utf-8")).hexdigest()[:6]
        slug = f"{slug}-{h}"
        path = scope_dir / f"{slug}.md"

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
    conn = connect(settings.db_path)
    repo = Repository(conn)
    repo.upsert_unit(unit)

    if supersedes:
        old = repo.get_unit(supersedes)
        if old is not None:
            repo.upsert_unit(replace(old, superseded_by=unit.id))

    return MemoryWriteResult(handle=unit.id, slug=slug, path=path)


def forget(settings: Settings, *, handle: str) -> None:
    conn = connect(settings.db_path)
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
            if "tombstoned: true" not in text:
                text = re.sub(r"^(---\n)", r"\1tombstoned: true\n", text, count=1)
                path.write_text(text, encoding="utf-8")

    _ensure_tombstone_unit(repo)
    repo.upsert_unit(replace(unit, superseded_by=TOMBSTONE_HANDLE))


def _ensure_tombstone_unit(repo: Repository) -> None:
    """Insert the sentinel tombstone unit if absent (satisfies FK constraint)."""
    if repo.get_unit(TOMBSTONE_HANDLE) is not None:
        return
    from ..units.model import Unit
    repo.upsert_unit(Unit(
        id=TOMBSTONE_HANDLE,
        layer="memory",
        kind="fact",
        scope="_tombstone",
        source_ref=None,
        content_hash="tombstone",
        t1_header="[tombstone] forgotten",
        created_at=0,
        last_seen_at=0,
    ))


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, max_chars: int = 40) -> str:
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return s[:max_chars] or "memory"

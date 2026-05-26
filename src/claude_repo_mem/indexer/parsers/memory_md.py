from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

from ...units.headers import t1_header
from ...units.ids import make_handle
from ...units.model import Unit
from ...units.typed import KIND_VALID_FOR_LAYER
from .base import ParseResult, now


VALID_KINDS = KIND_VALID_FOR_LAYER["memory"]
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


class MemoryMarkdownParser:
    def supports(self, path: Path) -> bool:
        if path.suffix.lower() not in (".md", ".markdown"):
            return False
        parts = [p.lower() for p in path.parts]
        try:
            i = parts.index(".claude-repo-mem")
        except ValueError:
            return False
        return i + 1 < len(parts) and parts[i + 1] == "memory"

    def parse(self, path: Path, text: str) -> ParseResult:
        m = FRONTMATTER_RE.match(text)
        front: dict = {}
        body = text
        if m:
            front = yaml.safe_load(m.group(1)) or {}
            body = text[m.end():]

        kind = (front.get("kind") or "fact").lower()
        if kind not in VALID_KINDS:
            raise ValueError(
                f"{path}: invalid memory kind {kind!r}; "
                f"must be one of {sorted(VALID_KINDS)}"
            )
        scope = front.get("scope") or _default_scope(path)
        confidence = front.get("confidence")
        confidence = float(confidence) if confidence is not None else None
        supersedes = front.get("supersedes")
        body = body.strip()

        uid = make_handle("memory", kind, f"{path.as_posix()}", body)
        content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        header = t1_header(layer="memory", kind=kind, text=body)

        metadata = {"body": body}
        if supersedes:
            metadata["supersedes"] = supersedes

        unit = Unit(
            id=uid,
            layer="memory",
            kind=kind,
            scope=scope,
            source_ref=path.as_posix(),
            content_hash=content_hash,
            t1_header=header,
            created_at=now(),
            last_seen_at=now(),
            confidence=confidence,
            metadata=json.dumps(metadata),
        )
        return ParseResult(units=[unit])


def _default_scope(path: Path) -> str:
    """Derive scope from the path under .claude-repo-mem/memory/."""
    parts = list(path.parts)
    try:
        i = [p.lower() for p in parts].index(".claude-repo-mem")
        scope_parts = parts[i + 2 : -1]
        return "/".join(scope_parts) if scope_parts else "root"
    except (ValueError, IndexError):
        return "root"

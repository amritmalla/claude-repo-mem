from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import yaml

from ...units.headers import t1_header
from ...units.ids import make_handle
from ...units.model import Unit
from .base import ParseResult, now


FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


class MarkdownParser:
    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in (".md", ".markdown")

    def parse(self, path: Path, text: str) -> ParseResult:
        front_meta, body, body_offset = _extract_frontmatter(text)
        default_scope = _scope_from_path(path)
        scope = (front_meta.get("scope") if front_meta else None) or default_scope

        units: List[Unit] = []
        parent_id: Optional[str] = None

        if front_meta is not None:
            fm_text = text[:body_offset]
            content_hash = _hash(fm_text)
            fid = make_handle("docs", "frontmatter", f"{path.as_posix()}#frontmatter", fm_text)
            units.append(
                Unit(
                    id=fid,
                    layer="docs",
                    kind="frontmatter",
                    scope=scope,
                    source_ref=f"{path.as_posix()}:0-{fm_text.count(chr(10))}",
                    content_hash=content_hash,
                    t1_header=f"# {path.stem} (frontmatter)",
                    created_at=now(),
                    last_seen_at=now(),
                    metadata=json.dumps({"raw": fm_text, "parsed": front_meta}),
                )
            )
            parent_id = fid

        sections = _split_sections(body, fallback_title=path.stem)
        for sec in sections:
            sid = make_handle("docs", "section", f"{path.as_posix()}#{'/'.join(sec.path)}", sec.body)
            units.append(
                Unit(
                    id=sid,
                    layer="docs",
                    kind="section",
                    scope=scope,
                    source_ref=f"{path.as_posix()}:{sec.start_line}-{sec.end_line}",
                    content_hash=_hash(sec.body),
                    t1_header=t1_header(layer="docs", kind="section", heading_path=sec.path),
                    parent_id=parent_id,
                    created_at=now(),
                    last_seen_at=now(),
                    metadata=sec.body,
                )
            )

        return ParseResult(units=units)


# -- helpers ---------------------------------------------------------------

def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _scope_from_path(path: Path) -> str:
    parts = path.parent.parts
    if not parts:
        return "root"
    return "/".join(parts)


def _extract_frontmatter(text: str):
    m = FRONTMATTER_RE.match(text)
    if not m:
        return None, text, 0
    try:
        parsed = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None, text, 0
    return parsed, text[m.end():], m.end()


@dataclass
class _Section:
    path: List[str]
    body: str
    start_line: int
    end_line: int


def _split_sections(body: str, fallback_title: str) -> List[_Section]:
    lines = body.splitlines()
    headings: List[tuple[int, int, str]] = []  # (line_idx, level, text)
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            headings.append((i, len(m.group(1)), m.group(2).strip()))

    if not headings:
        return [_Section(path=[fallback_title], body=body, start_line=0, end_line=len(lines))]

    sections: List[_Section] = []
    stack: List[str] = []   # current heading path
    levels: List[int] = []  # heading levels matching stack
    for idx, (line_idx, level, text) in enumerate(headings):
        # pop deeper-or-equal levels
        while levels and levels[-1] >= level:
            stack.pop()
            levels.pop()
        stack.append(text)
        levels.append(level)
        end_line = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        body_lines = lines[line_idx + 1 : end_line]
        sections.append(_Section(path=list(stack), body="\n".join(body_lines).strip(),
                                 start_line=line_idx, end_line=end_line))
    return sections

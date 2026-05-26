from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ChatTurn:
    role: str
    content: str


def find_latest_transcript(repo_root: Path, override: Optional[Path] = None) -> Optional[Path]:
    """Find the most recent Claude Code transcript matching this repo.

    Returns None if no match. If `override` is given, returns it unchanged.
    """
    if override is not None:
        return override
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.is_dir():
        return None
    repo_marker = str(repo_root.resolve()).replace("\\", "/").replace(":", "").replace("/", "-").lower()
    best: Optional[Path] = None
    best_mtime = -1.0
    for jsonl in projects_dir.rglob("*.jsonl"):
        # Match by slug containing repo dir name (loose, since slug format varies).
        slug = jsonl.parent.name.lower()
        if repo_root.name.lower() not in slug:
            continue
        m = jsonl.stat().st_mtime
        if m > best_mtime:
            best_mtime = m
            best = jsonl
    return best


def parse_transcript(path: Path) -> list[ChatTurn]:
    """Parse JSONL transcript, normalizing each line to a ChatTurn."""
    turns: list[ChatTurn] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            role, content = _extract_role_content(event)
            if role and content:
                turns.append(ChatTurn(role=role, content=content))
    return turns


def _extract_role_content(event: dict) -> tuple[Optional[str], Optional[str]]:
    msg = event.get("message") if isinstance(event.get("message"), dict) else event
    role = msg.get("role") if isinstance(msg, dict) else None
    raw = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(raw, str):
        return role, raw
    if isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        if parts:
            return role, "\n".join(parts)
    return role, None

from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from ..config import Settings
from ..llm.base import LLMClient
from ..memory.writer import remember, MemoryWriteResult
from .extract import Proposal, extract_memories, proposal_dedupe_key
from .transcript import find_latest_transcript, parse_transcript


def dedupe_proposals(proposals: list[Proposal], threshold: float = 0.85) -> list[Proposal]:
    """Collapse near-duplicate proposals (same scope, ratio >= threshold).

    Higher-confidence proposals win. Proposals in different scopes never dedupe.
    """
    out: list[Proposal] = []
    for p in sorted(proposals, key=lambda x: -x.confidence):
        is_dup = False
        for kept in out:
            if kept.scope != p.scope:
                continue
            ratio = SequenceMatcher(
                None, proposal_dedupe_key(kept), proposal_dedupe_key(p)
            ).ratio()
            if ratio >= threshold:
                is_dup = True
                break
        if not is_dup:
            out.append(p)
    return out


def group_by_scope(proposals: list[Proposal]) -> dict[str, list[Proposal]]:
    """Group proposals by scope; within each scope sort by confidence desc."""
    groups: dict[str, list[Proposal]] = {}
    for p in proposals:
        groups.setdefault(p.scope, []).append(p)
    for k in groups:
        groups[k].sort(key=lambda p: -p.confidence)
    return groups


async def run_distill(
    settings: Settings,
    *,
    llm: LLMClient,
    transcript_path: Optional[Path] = None,
    auto_accept: bool = False,
    prompt_fn=None,
) -> dict:
    """Locate transcript, extract proposals, prompt user, write accepted ones.

    `prompt_fn(proposal) -> 'a'|'e'|'s'|'q'` is injected for testability.
    """
    path = find_latest_transcript(settings.repo_root, transcript_path)
    if path is None or not path.exists():
        return {"transcript": None, "proposals": 0, "written": 0}

    turns = parse_transcript(path)
    proposals = await extract_memories(turns, llm)
    proposals = dedupe_proposals(proposals)

    written: list[MemoryWriteResult] = []
    for p in proposals:
        if auto_accept:
            decision = "a"
        elif prompt_fn is not None:
            decision = prompt_fn(p)
        else:
            decision = "s"
        if decision == "q":
            break
        if decision == "a":
            r = remember(
                settings, fact=p.fact, scope=p.scope, kind=p.kind, confidence=p.confidence,
            )
            written.append(r)

    return {
        "transcript": str(path),
        "proposals": len(proposals),
        "written": len(written),
        "handles": [w.handle for w in written],
    }

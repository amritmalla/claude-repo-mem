from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from ..llm.base import LLMClient, LLMError
from .transcript import ChatTurn


EXTRACT_SYSTEM = """\
You extract DURABLE engineering knowledge from a Claude Code session transcript.

Durable means: a decision, convention, preference, or fact about THIS repo that
will still be relevant in a future session. NOT ephemeral debugging steps,
incidental tool outputs, or work-in-progress reasoning.

For each durable item, propose:
- kind: fact | decision | preference | convention
- scope: a slash-path like "backend/auth" or "tooling/build" — match the
  conceptual area the item applies to
- confidence: 0..1 (1.0 means the user stated this explicitly; lower means
  inferred)
- fact: 1-2 sentence statement, no preamble

Respond ONLY with JSON: {"proposals": [{"kind": ..., "scope": ..., "confidence": ..., "fact": ...}]}

If there's nothing durable, return {"proposals": []}.
"""


@dataclass
class Proposal:
    fact: str
    scope: str
    kind: str
    confidence: float


async def extract_memories(turns: list[ChatTurn], llm: LLMClient) -> list[Proposal]:
    if not turns:
        return []
    rendered = "\n\n".join(f"[{t.role.upper()}]\n{t.content}" for t in turns)
    user = f"Transcript:\n\n{rendered[:30000]}\n\nExtract durable memories."
    try:
        raw = await llm.complete(
            system=EXTRACT_SYSTEM, user=user, max_tokens=2000, temperature=0.0
        )
    except LLMError:
        return []
    try:
        data = json.loads(raw)
        proposals = data.get("proposals") or []
    except (json.JSONDecodeError, AttributeError, TypeError):
        return []
    out: list[Proposal] = []
    for p in proposals:
        if not isinstance(p, dict):
            continue
        fact = (p.get("fact") or "").strip()
        scope = (p.get("scope") or "root").strip() or "root"
        kind = (p.get("kind") or "fact").lower()
        conf = p.get("confidence")
        try:
            conf_f = float(conf) if conf is not None else 0.5
        except (TypeError, ValueError):
            conf_f = 0.5
        if not fact:
            continue
        if kind not in ("fact", "decision", "preference", "convention"):
            kind = "fact"
        out.append(Proposal(fact=fact, scope=scope, kind=kind, confidence=conf_f))
    return out


import re as _re


_STOP = {"a", "an", "the", "is", "are", "was", "were", "be", "been", "to", "for",
         "of", "in", "on", "we", "you", "i", "it", "this", "that", "use", "used",
         "uses", "using", "and", "or", "but", "so", "as", "by", "with"}


def proposal_dedupe_key(p: Proposal) -> str:
    """Order-insensitive normalized fingerprint for fuzzy duplicate detection.

    Stems tokens to their first 4 chars and drops stopwords so that
    "We use RS256 for JWT signing." and "RS256 is used to sign JWTs."
    produce overlapping keys.
    """
    text = _re.sub(r"[^\w\s]", " ", p.fact.lower())
    tokens = [t[:4] for t in text.split() if t not in _STOP and len(t) > 1]
    return f"{p.scope}::" + " ".join(sorted(set(tokens)))

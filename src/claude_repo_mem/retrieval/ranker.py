from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping

from ..db.repository import SearchHit
from ..units.model import Unit


RRF_K = 60
RECENCY_HALF_LIFE_DAYS = 30
LAYER_MULT = {"memory": 1.5, "docs": 1.1, "code": 1.0, "task": 1.3}


@dataclass(frozen=True)
class RankedItem:
    unit: Unit
    score: float
    rank: int


def rrf_then_rerank(
    bm25: Iterable[SearchHit],
    vec: Iterable[SearchHit],
    units_by_id: Mapping[str, Unit],
    query_scope: str | None,
    include_superseded: bool = False,
) -> List[RankedItem]:
    rrf: Dict[str, float] = {}
    for h in bm25:
        rrf[h.id] = rrf.get(h.id, 0.0) + 1.0 / (RRF_K + h.rank)
    for h in vec:
        rrf[h.id] = rrf.get(h.id, 0.0) + 1.0 / (RRF_K + h.rank)

    scored: List[tuple[float, Unit]] = []
    now = int(time.time())
    for uid, fusion in rrf.items():
        u = units_by_id.get(uid)
        if u is None:
            continue
        if u.superseded_by and not include_superseded:
            continue
        s = fusion
        s *= _scope_mult(u.scope, query_scope)
        s *= _recency_mult(u.last_seen_at, now)
        s *= LAYER_MULT.get(u.layer, 1.0)
        scored.append((s, u))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [RankedItem(unit=u, score=s, rank=i + 1) for i, (s, u) in enumerate(scored)]


def _scope_mult(unit_scope: str, query_scope: str | None) -> float:
    if not query_scope:
        return 1.0
    if unit_scope == query_scope:
        return 1.0
    # Sibling = share at least one parent component
    u_parts = unit_scope.split("/")
    q_parts = query_scope.split("/")
    shared = 0
    for a, b in zip(u_parts, q_parts):
        if a == b:
            shared += 1
        else:
            break
    if shared >= 1:
        return 0.7
    return 0.4


def _recency_mult(last_seen_at: int, now: int) -> float:
    age_days = max(0, (now - last_seen_at) / 86400.0)
    decay = math.exp(-age_days * math.log(2) / RECENCY_HALF_LIFE_DAYS)
    return 0.5 + 0.5 * decay

from __future__ import annotations

import time
from collections import deque
from typing import Optional, Sequence

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository
from ..units.model import Unit
from .fill import FillResult, budget_fill
from .ranker import RankedItem, _recency_mult, LAYER_MULT


DEFAULT_BUDGET = 8000
DEFAULT_DEPTH = 2
MAX_DEPTH = 3

# Relation-kind weights — higher = pulled in earlier
REL_WEIGHTS = {
    "route_to": 1.0,
    "implements": 0.9,
    "mentions": 0.6,
    "imports": 0.5,
    "child_task": 0.8,
}


def trace(
    settings: Settings,
    *,
    seeds: Sequence[str],
    depth: int = DEFAULT_DEPTH,
    budget: int = DEFAULT_BUDGET,
    relations: Optional[Sequence[str]] = None,
) -> FillResult:
    if depth > MAX_DEPTH:
        depth = MAX_DEPTH
    conn = connect(settings.db_path)
    repo = Repository(conn)

    # BFS, collecting (id, hop_distance, best_relation_weight)
    seen: dict[str, tuple[int, float]] = {sid: (0, 1.0) for sid in seeds}
    queue: deque[tuple[str, int]] = deque((sid, 0) for sid in seeds)
    while queue:
        node, hop = queue.popleft()
        if hop >= depth:
            continue
        out = repo.neighbors(node, direction="out", kinds=list(relations) if relations else None)
        inn = repo.neighbors(node, direction="in", kinds=list(relations) if relations else None)
        for rel in out + inn:
            neighbor = rel.dst_id if rel.src_id == node else rel.src_id
            w = REL_WEIGHTS.get(rel.kind, 0.3)
            prev = seen.get(neighbor)
            new_hop = hop + 1
            if prev is None or new_hop < prev[0] or w > prev[1]:
                seen[neighbor] = (new_hop, w)
                queue.append((neighbor, new_hop))

    units = repo.get_units(list(seen.keys()))
    units_by_id = {u.id: u for u in units}

    now = int(time.time())
    ranked_items: list[RankedItem] = []
    for uid, (hop, rel_w) in seen.items():
        u = units_by_id.get(uid)
        if u is None:
            continue
        if u.superseded_by:
            continue
        hop_factor = 1.0 / (1.0 + hop)   # seeds: 1.0, hop 1: 0.5, hop 2: 0.33
        score = hop_factor * rel_w * LAYER_MULT.get(u.layer, 1.0) * _recency_mult(u.last_seen_at, now)
        ranked_items.append(RankedItem(unit=u, score=score, rank=0))

    ranked_items.sort(key=lambda r: r.score, reverse=True)
    # Re-assign ranks now that sort is stable
    ranked_items = [RankedItem(unit=r.unit, score=r.score, rank=i + 1)
                    for i, r in enumerate(ranked_items)]

    def content_fn(u: Unit, tier: str) -> str:
        if tier == "T0":
            return u.metadata or u.t2_summary or u.t1_header
        if tier == "T2":
            return u.t2_summary or u.t1_header
        return u.t1_header

    return budget_fill(ranked_items, content_fn, budget=budget)

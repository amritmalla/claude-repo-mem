from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List

from ..tokens import count_tokens
from ..units.model import Unit
from .ranker import RankedItem


TOP_PROMOTE = 5
T0_SINGLE_CAP_FRACTION = 0.4


@dataclass(frozen=True)
class FilledItem:
    handle: str
    tier: str       # "T0" | "T2" | "T1"
    content: str
    rank: int
    score: float
    scope: str
    layer: str


@dataclass(frozen=True)
class FillResult:
    items: List[FilledItem]
    overflow_handles: List[str]
    budget_used: int
    budget_total: int
    tier_histogram: Dict[str, int]


ContentFn = Callable[[Unit, str], str]


def budget_fill(
    ranked: List[RankedItem],
    content_fn: ContentFn,
    budget: int,
    top_promote: int = TOP_PROMOTE,
    t0_single_cap_fraction: float = T0_SINGLE_CAP_FRACTION,
) -> FillResult:
    items: List[FilledItem] = []
    overflow: List[str] = []
    used = 0
    hist = {"T0": 0, "T2": 0, "T1": 0}

    for ri in ranked:
        remaining = budget - used
        if remaining <= 0:
            overflow.append(ri.unit.id)
            continue

        # Attempt T0 promotion for top-ranked units
        chosen_tier = None
        chosen_content = None
        chosen_tokens = 0

        if ri.rank <= top_promote:
            t0 = content_fn(ri.unit, "T0")
            t = count_tokens(t0)
            cap = int(remaining * t0_single_cap_fraction)
            if t > 0 and t <= cap:
                chosen_tier, chosen_content, chosen_tokens = "T0", t0, t

        if chosen_tier is None:
            t2 = content_fn(ri.unit, "T2")
            t = count_tokens(t2)
            if t > 0 and t <= remaining:
                chosen_tier, chosen_content, chosen_tokens = "T2", t2, t

        if chosen_tier is None:
            t1 = content_fn(ri.unit, "T1")
            t = count_tokens(t1)
            if t > 0 and t <= remaining:
                chosen_tier, chosen_content, chosen_tokens = "T1", t1, t

        if chosen_tier is None:
            overflow.append(ri.unit.id)
            continue

        items.append(FilledItem(
            handle=ri.unit.id,
            tier=chosen_tier,
            content=chosen_content,
            rank=ri.rank,
            score=ri.score,
            scope=ri.unit.scope,
            layer=ri.unit.layer,
        ))
        used += chosen_tokens
        hist[chosen_tier] += 1

    return FillResult(
        items=items,
        overflow_handles=overflow,
        budget_used=used,
        budget_total=budget,
        tier_histogram=hist,
    )

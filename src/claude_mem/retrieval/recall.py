from __future__ import annotations

import re
from typing import Optional, Sequence

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository
from ..embeddings.base import Embedder
from ..units.model import Unit
from .fill import FillResult, budget_fill
from .ranker import rrf_then_rerank


DEFAULT_BUDGET = 3000
TOP_K = 100


def recall(
    settings: Settings,
    *,
    query: str,
    embedder: Embedder,
    budget: int = DEFAULT_BUDGET,
    scopes: Optional[Sequence[str]] = None,
    layers: Optional[Sequence[str]] = None,
    include_superseded: bool = False,
) -> FillResult:
    conn = connect(settings.db_path)
    repo = Repository(conn)

    # FTS query: simple word-tokenized, OR'd.
    fts_query = " OR ".join(_fts_tokens(query)) or query
    bm25_hits = repo.fts_search(fts_query, limit=TOP_K)

    # Vector query.
    [qvec] = embedder.embed([query])
    vec_hits = repo.vec_search(qvec, limit=TOP_K)

    # Fetch units for the union of ids.
    all_ids = {h.id for h in bm25_hits} | {h.id for h in vec_hits}
    units = repo.get_units(list(all_ids))

    # Optional layer/scope filtering (pre-rank, hard).
    if layers:
        units = [u for u in units if u.layer in layers]
    if scopes:
        units = [u for u in units if any(_scope_match(u.scope, s) for s in scopes)]
    units_by_id = {u.id: u for u in units}

    ranked = rrf_then_rerank(
        bm25_hits, vec_hits, units_by_id,
        query_scope=scopes[0] if scopes else None,
        include_superseded=include_superseded,
    )

    def content_fn(u: Unit, tier: str) -> str:
        if tier == "T0":
            return u.metadata or u.t2_summary or u.t1_header
        if tier == "T2":
            return u.t2_summary or u.t1_header
        return u.t1_header

    return budget_fill(ranked, content_fn, budget=budget)


def _fts_tokens(query: str) -> list[str]:
    return [w for w in re.findall(r"\w+", query) if len(w) > 1]


def _scope_match(unit_scope: str, query_scope: str) -> bool:
    return unit_scope == query_scope or unit_scope.startswith(query_scope + "/")

import time
from claude_repo_mem.retrieval.ranker import rrf_then_rerank, RankedItem
from claude_repo_mem.db.repository import SearchHit
from claude_repo_mem.units.model import Unit


def _u(id, scope="x", layer="code", days_old=0, superseded=False) -> Unit:
    t = int(time.time() - days_old * 86400)
    return Unit(
        id=id, layer=layer, kind="function", scope=scope,
        source_ref=None, content_hash="h", t1_header=f"header for {id}",
        created_at=t, last_seen_at=t,
        superseded_by="x" if superseded else None,
    )


def test_rrf_combines_two_lists():
    units = {"a": _u("a"), "b": _u("b"), "c": _u("c")}
    bm25 = [SearchHit("a", 1, 0.0), SearchHit("c", 2, 0.0)]
    vec = [SearchHit("b", 1, 0.0), SearchHit("a", 2, 0.0)]
    ranked = rrf_then_rerank(bm25, vec, units, query_scope="x")
    ids = [r.unit.id for r in ranked]
    # 'a' appears in both lists at low rank → should be at or near the top
    assert ids[0] == "a"


def test_superseded_filtered_by_default():
    units = {"a": _u("a"), "b": _u("b", superseded=True)}
    bm25 = [SearchHit("b", 1, 0.0), SearchHit("a", 2, 0.0)]
    vec: list[SearchHit] = []
    ranked = rrf_then_rerank(bm25, vec, units, query_scope="x")
    assert all(r.unit.id != "b" for r in ranked)


def test_scope_match_boosts():
    units = {"hit": _u("hit", scope="backend/auth"),
             "miss": _u("miss", scope="frontend/ui")}
    bm25 = [SearchHit("miss", 1, 0.0), SearchHit("hit", 2, 0.0)]
    vec: list[SearchHit] = []
    ranked = rrf_then_rerank(bm25, vec, units, query_scope="backend/auth")
    # exact-scope match should overcome a one-rank deficit
    assert ranked[0].unit.id == "hit"


def test_layer_boost_memory_wins():
    units = {"mem": _u("mem", layer="memory"), "code": _u("code", layer="code")}
    bm25 = [SearchHit("code", 1, 0.0), SearchHit("mem", 2, 0.0)]
    vec: list[SearchHit] = []
    ranked = rrf_then_rerank(bm25, vec, units, query_scope="x")
    assert ranked[0].unit.id == "mem"


def test_recency_decay():
    units = {"new": _u("new", days_old=0), "old": _u("old", days_old=120)}
    bm25 = [SearchHit("old", 1, 0.0), SearchHit("new", 2, 0.0)]
    vec: list[SearchHit] = []
    ranked = rrf_then_rerank(bm25, vec, units, query_scope="x")
    assert ranked[0].unit.id == "new"


def test_include_superseded():
    units = {"a": _u("a"), "b": _u("b", superseded=True)}
    bm25 = [SearchHit("b", 1, 0.0)]
    vec: list[SearchHit] = []
    ranked = rrf_then_rerank(bm25, vec, units, query_scope="x", include_superseded=True)
    assert any(r.unit.id == "b" for r in ranked)

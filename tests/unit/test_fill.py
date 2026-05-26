from claude_repo_mem.retrieval.fill import budget_fill, FilledItem, FillResult
from claude_repo_mem.retrieval.ranker import RankedItem
from claude_repo_mem.units.model import Unit


def _ri(id, rank, t1="t1", t2=None, t0=None) -> RankedItem:
    u = Unit(id=id, layer="code", kind="function", scope="x",
             source_ref=None, content_hash="h", t1_header=t1,
             t2_summary=t2, created_at=0, last_seen_at=0, metadata=t0)
    return RankedItem(unit=u, score=1.0 / rank, rank=rank)


def _content(unit: Unit, tier: str) -> str:
    if tier == "T1":
        return unit.t1_header
    if tier == "T2":
        return unit.t2_summary or unit.t1_header
    return unit.metadata or unit.t1_header


def test_top_result_promoted_to_t0_when_fits():
    ranked = [_ri("a", 1, t1="short", t2="medium summary", t0="x" * 50)]
    res = budget_fill(ranked, _content, budget=1000)
    assert res.items[0].tier == "T0"
    assert res.items[0].content == "x" * 50


def test_oversized_t0_falls_back_to_t2():
    huge = "x" * 100_000
    ranked = [_ri("a", 1, t1="t1", t2="t2 summary", t0=huge)]
    res = budget_fill(ranked, _content, budget=500)
    assert res.items[0].tier == "T2"


def test_low_rank_does_not_promote_to_t0():
    ranked = [_ri(f"u{i}", i + 1, t1="t1", t2="t2 summary", t0="x" * 50) for i in range(10)]
    res = budget_fill(ranked, _content, budget=10_000, top_promote=3)
    # First 3 may be T0; 4+ must be T2 or T1
    for item in res.items[3:]:
        assert item.tier in ("T2", "T1")


def test_overflow_when_budget_exhausted():
    ranked = [_ri(f"u{i}", i + 1, t1="x" * 50) for i in range(100)]
    res = budget_fill(ranked, _content, budget=200)
    assert len(res.overflow_handles) > 0
    assert res.budget_used <= 200


def test_tier_histogram():
    ranked = [_ri(f"u{i}", i + 1, t1="t1", t2="medium summary", t0="x" * 30) for i in range(5)]
    res = budget_fill(ranked, _content, budget=10_000, top_promote=2)
    total = sum(res.tier_histogram.values())
    assert total == len(res.items)

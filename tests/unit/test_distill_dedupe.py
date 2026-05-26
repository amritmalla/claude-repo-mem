from claude_mem.distill.extract import Proposal
from claude_mem.distill.confirm import dedupe_proposals, group_by_scope


def test_dedupe_collapses_near_duplicate():
    a = Proposal(fact="We use RS256 for JWT signing.", scope="backend/auth", kind="decision", confidence=0.9)
    b = Proposal(fact="RS256 is used to sign JWTs.", scope="backend/auth", kind="decision", confidence=0.7)
    out = dedupe_proposals([a, b])
    assert len(out) == 1
    assert out[0].confidence == 0.9


def test_dedupe_keeps_distinct():
    a = Proposal(fact="We use RS256.", scope="backend/auth", kind="decision", confidence=0.9)
    b = Proposal(fact="Tests run pytest -q.", scope="tooling", kind="convention", confidence=0.8)
    out = dedupe_proposals([a, b])
    assert len(out) == 2


def test_dedupe_does_not_merge_across_scopes():
    a = Proposal(fact="We use RS256.", scope="backend/auth", kind="decision", confidence=0.9)
    b = Proposal(fact="We use RS256.", scope="frontend/api", kind="decision", confidence=0.6)
    out = dedupe_proposals([a, b])
    assert len(out) == 2


def test_group_by_scope_orders_by_confidence_desc():
    a = Proposal(fact="A", scope="x", kind="fact", confidence=0.5)
    b = Proposal(fact="B", scope="x", kind="fact", confidence=0.9)
    c = Proposal(fact="C", scope="y", kind="fact", confidence=0.7)
    groups = group_by_scope([a, b, c])
    assert set(groups.keys()) == {"x", "y"}
    assert groups["x"][0].confidence == 0.9
    assert groups["x"][1].confidence == 0.5
    assert groups["y"][0].confidence == 0.7

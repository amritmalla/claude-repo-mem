"""Phase 5 acceptance — pluggable embedders, queue-driven backfill, bench, dedupe."""
from pathlib import Path
import yaml
import pytest
from unittest.mock import AsyncMock
import numpy as np

from claude_mem.config import Settings
from claude_mem.db.connection import init_db, connect
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.queue.background import BackgroundQueue
from claude_mem.summarizer.backfill import enqueue_backfill
from claude_mem.bench.runner import run_benchmark
from claude_mem.distill.confirm import dedupe_proposals
from claude_mem.distill.extract import Proposal


class _FakeEmbedder:
    name, dim = "fake8", 8

    def embed(self, texts):
        return [np.zeros(8, dtype="float32") for _ in texts]


def test_phase5_end_to_end(tmp_repo: Path):
    # 1. Pluggable embedder is recorded.
    (tmp_repo / "auth.py").write_text(
        "def login_user(user, pw):\n    " + "x = 1\n    " * 30 + "return user\n"
    )
    s = Settings.for_repo(tmp_repo); init_db(s.db_path, dim=8)
    full_reindex(s, embedder=_FakeEmbedder())
    meta = connect(s.db_path).execute("SELECT name, dim FROM embedder_meta").fetchone()
    assert meta["name"] == "fake8" and meta["dim"] == 8

    # 2. Backfill via queue populates T2.
    q = BackgroundQueue(); q.start()
    try:
        llm = AsyncMock(); llm.complete = AsyncMock(return_value="queue summary")
        enqueue_backfill(s, llm=llm, queue=q)
        q.drain(timeout=10.0)
        n = connect(s.db_path).execute(
            "SELECT COUNT(*) FROM unit WHERE t2_summary IS NOT NULL"
        ).fetchone()[0]
        assert n >= 1
    finally:
        q.stop()

    # 3. Bench harness reports recall.
    fixture = tmp_repo / "q.yaml"
    fixture.write_text(yaml.safe_dump({
        "queries": [{"q": "login", "expect_header_substring": "login"}],
    }))
    result = run_benchmark(s, fixture, embedder=None, k=5)
    assert result.recall_at_k == 1.0

    # 4. Distill dedupe collapses near-duplicates within a scope.
    a = Proposal(fact="RS256 over HS256 for gateway verification.",
                 scope="auth", kind="decision", confidence=0.9)
    b = Proposal(fact="RS256 over HS256 to let the gateway verify.",
                 scope="auth", kind="decision", confidence=0.7)
    out = dedupe_proposals([a, b])
    assert len(out) == 1
    assert out[0].confidence == 0.9

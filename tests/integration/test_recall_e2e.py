from pathlib import Path
import numpy as np
import pytest

from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db, connect
from claude_repo_mem.db.repository import Repository
from claude_repo_mem.indexer.orchestrator import full_reindex
from claude_repo_mem.retrieval.recall import recall


class FakeEmbedder:
    dim = 384

    def __init__(self):
        self._cache: dict[str, np.ndarray] = {}

    def embed(self, texts):
        out = []
        for t in texts:
            # Deterministic hash → 384-dim unit vector
            seed = abs(hash(t)) % (2**31)
            rng = np.random.default_rng(seed)
            v = rng.standard_normal(384).astype("float32")
            v /= np.linalg.norm(v) + 1e-8
            out.append(v)
        return out


@pytest.fixture
def indexed_repo(tmp_repo: Path):
    (tmp_repo / "auth.py").write_text(
        "def login(user, pw):\n    return 'token for ' + user\n\n"
        "def logout(user):\n    return 'bye ' + user\n"
    )
    (tmp_repo / "docs.md").write_text("# Auth\n\nWe use token-based login.\n")
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=FakeEmbedder())
    return s


def test_recall_returns_items(indexed_repo):
    result = recall(indexed_repo, query="login", budget=3000, embedder=FakeEmbedder())
    assert len(result.items) >= 1
    assert result.budget_used <= 3000


def test_recall_respects_budget(indexed_repo):
    result = recall(indexed_repo, query="login", budget=100, embedder=FakeEmbedder())
    assert result.budget_used <= 100


def test_recall_scope_filter(indexed_repo):
    # docs.md and auth.py are both at scope "root" in this fixture.
    result = recall(indexed_repo, query="login", budget=3000, embedder=FakeEmbedder(), scopes=["root"])
    assert all(item.scope == "root" for item in result.items)


def test_recall_layer_filter(indexed_repo):
    result = recall(indexed_repo, query="login", budget=3000, embedder=FakeEmbedder(), layers=["code"])
    assert all(item.layer == "code" for item in result.items)


def test_recall_tier_histogram_sums(indexed_repo):
    result = recall(indexed_repo, query="login", budget=3000, embedder=FakeEmbedder())
    assert sum(result.tier_histogram.values()) == len(result.items)

from pathlib import Path
import numpy as np
import pytest

from claude_mem.config import Settings
from claude_mem.db.connection import init_db
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.retrieval.recall import recall
from claude_mem.retrieval.trace import trace
from tests.integration.test_recall_e2e import FakeEmbedder


@pytest.fixture
def flask_repo(tmp_repo: Path):
    (tmp_repo / "app.py").write_text(
        "from flask import Flask\n"
        "app = Flask(__name__)\n\n"
        "@app.route('/login', methods=['POST'])\n"
        "def login():\n"
        "    return verify_user()\n\n"
        "def verify_user():\n"
        "    return 'ok'\n"
    )
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=FakeEmbedder())
    return s


def test_trace_from_route_finds_handler(flask_repo):
    # Find the route unit
    result = recall(flask_repo, query="/login", budget=3000, embedder=FakeEmbedder())
    route = next((it for it in result.items if "route" in it.handle), None)
    assert route is not None

    trace_result = trace(flask_repo, seeds=[route.handle], depth=2, budget=8000)
    handles = {it.handle for it in trace_result.items}
    # Should include the seed and the handler
    assert route.handle in handles
    assert any("function" in h for h in handles)


def test_trace_depth_limit(flask_repo):
    result = recall(flask_repo, query="login", budget=3000, embedder=FakeEmbedder())
    seed = result.items[0].handle
    r1 = trace(flask_repo, seeds=[seed], depth=1, budget=8000)
    r2 = trace(flask_repo, seeds=[seed], depth=2, budget=8000)
    assert len(r2.items) >= len(r1.items)


def test_trace_respects_budget(flask_repo):
    result = recall(flask_repo, query="login", budget=3000, embedder=FakeEmbedder())
    seed = result.items[0].handle
    r = trace(flask_repo, seeds=[seed], depth=2, budget=100)
    assert r.budget_used <= 100

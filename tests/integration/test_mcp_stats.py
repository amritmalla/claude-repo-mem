import json
import pytest
from pathlib import Path
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db
from claude_repo_mem.indexer.orchestrator import full_reindex
from claude_repo_mem.tools.stats import handle, tool_schema


@pytest.fixture
def indexed(tmp_repo: Path):
    (tmp_repo / "x.py").write_text("def x(): pass\n")
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=None)
    return s


def test_schema():
    assert tool_schema().name == "stats"


@pytest.mark.asyncio
async def test_returns_counts(indexed):
    out = await handle(indexed, {})
    payload = json.loads(out[0].text)
    assert "total_units" in payload
    assert "by_layer" in payload
    assert "counters" in payload

import json
import pytest
from pathlib import Path
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db
from claude_repo_mem.indexer.orchestrator import full_reindex
from claude_repo_mem.tools.scopes import handle, tool_schema


@pytest.fixture
def indexed(tmp_repo: Path):
    (tmp_repo / "backend").mkdir()
    (tmp_repo / "backend" / "auth").mkdir()
    (tmp_repo / "backend" / "auth" / "jwt.py").write_text("def x(): pass\n")
    (tmp_repo / "frontend").mkdir()
    (tmp_repo / "frontend" / "ui.py").write_text("def y(): pass\n")
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=None)
    return s


def test_schema():
    assert tool_schema().name == "scopes"


@pytest.mark.asyncio
async def test_lists_scopes_with_counts(indexed):
    out = await handle(indexed, {})
    payload = json.loads(out[0].text)
    by_scope = {s["scope"]: s["count"] for s in payload["scopes"]}
    assert "backend/auth" in by_scope
    assert "frontend" in by_scope
    assert all(c > 0 for c in by_scope.values())

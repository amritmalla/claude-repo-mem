import json
from pathlib import Path
import pytest

from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db
from claude_repo_mem.indexer.orchestrator import full_reindex
from claude_repo_mem.tools.recall import handle, tool_schema
from tests.integration.test_recall_e2e import FakeEmbedder


@pytest.fixture
def settings_with_index(tmp_repo: Path):
    (tmp_repo / "auth.py").write_text("def login(user, pw):\n    return 'token'\n")
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=FakeEmbedder())
    return s


def test_schema_has_required_fields():
    s = tool_schema()
    assert s.name == "recall"
    assert "query" in s.inputSchema["properties"]
    assert "budget" in s.inputSchema["properties"]
    assert "query" in s.inputSchema.get("required", [])


@pytest.mark.asyncio
async def test_handle_returns_json(settings_with_index):
    out = await handle(settings_with_index, FakeEmbedder(), {"query": "login", "budget": 3000})
    assert len(out) == 1
    payload = json.loads(out[0].text)
    assert "items" in payload
    assert "budget_used" in payload
    assert "tier_histogram" in payload


@pytest.mark.asyncio
async def test_default_budget_is_3000(settings_with_index):
    out = await handle(settings_with_index, FakeEmbedder(), {"query": "login"})
    payload = json.loads(out[0].text)
    assert payload["budget_total"] == 3000

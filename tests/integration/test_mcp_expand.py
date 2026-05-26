import json
from pathlib import Path
import pytest

from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db
from claude_repo_mem.indexer.orchestrator import full_reindex
from claude_repo_mem.tools.recall import handle as recall_handle
from claude_repo_mem.tools.expand import handle, tool_schema
from tests.integration.test_recall_e2e import FakeEmbedder


@pytest.fixture
def settings_with_index(tmp_repo: Path):
    (tmp_repo / "auth.py").write_text(
        "def login(user, pw):\n    return 'token for ' + user + pw\n"
    )
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=FakeEmbedder())
    return s


def test_schema():
    s = tool_schema()
    assert s.name == "expand"
    assert "handle" in s.inputSchema["properties"]
    assert "tier" in s.inputSchema["properties"]


@pytest.mark.asyncio
async def test_expand_t0_returns_source(settings_with_index):
    recall_out = await recall_handle(settings_with_index, FakeEmbedder(), {"query": "login"})
    items = json.loads(recall_out[0].text)["items"]
    code_handle = next(h["handle"] for h in items if h["layer"] == "code")
    out = await handle(settings_with_index, {"handle": code_handle, "tier": "T0"})
    payload = json.loads(out[0].text)
    assert "content" in payload
    assert "def login" in payload["content"]


@pytest.mark.asyncio
async def test_expand_unknown_handle_returns_error(settings_with_index):
    out = await handle(settings_with_index, {"handle": "code://function/nope", "tier": "T0"})
    payload = json.loads(out[0].text)
    assert "error" in payload

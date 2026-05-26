import json
from pathlib import Path
import pytest
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db
from claude_repo_mem.tools.remember import handle, tool_schema


@pytest.fixture
def settings(tmp_repo: Path):
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    return s


def test_schema():
    s = tool_schema()
    assert s.name == "remember"
    props = s.inputSchema["properties"]
    assert "fact" in props
    assert "scope" in props
    assert "kind" in props
    assert {"fact", "scope"}.issubset(set(s.inputSchema.get("required", [])))


@pytest.mark.asyncio
async def test_handle_writes_memory(settings):
    out = await handle(settings, {"fact": "We use JWT.", "scope": "backend/auth"})
    payload = json.loads(out[0].text)
    assert payload["handle"].startswith("memory://")
    assert "path" in payload


@pytest.mark.asyncio
async def test_handle_invalid_kind_returns_error(settings):
    out = await handle(settings, {"fact": "x", "scope": "x", "kind": "bogus"})
    payload = json.loads(out[0].text)
    assert "error" in payload

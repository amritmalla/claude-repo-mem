import json
from pathlib import Path
import pytest

from claude_mem.config import Settings
from claude_mem.db.connection import init_db
from claude_mem.indexer.orchestrator import full_reindex
from claude_mem.tools.recall import handle as recall_handle
from claude_mem.tools.trace import handle as trace_handle, tool_schema
from tests.integration.test_recall_e2e import FakeEmbedder


@pytest.fixture
def settings_with_flask(tmp_repo: Path):
    (tmp_repo / "app.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\n\n"
        "@app.route('/login', methods=['POST'])\n"
        "def login():\n    return 'ok'\n"
    )
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=FakeEmbedder())
    return s


def test_schema_required():
    s = tool_schema()
    assert s.name == "trace"
    assert "seed_handles" in s.inputSchema["properties"]
    assert "seed_handles" in s.inputSchema.get("required", [])


@pytest.mark.asyncio
async def test_handle_traces_from_recall_seed(settings_with_flask):
    recall_out = await recall_handle(settings_with_flask, FakeEmbedder(),
                                      {"query": "login"})
    items = json.loads(recall_out[0].text)["items"]
    assert items, "need at least one item to seed trace"
    seed = items[0]["handle"]
    out = await trace_handle(settings_with_flask, {"seed_handles": [seed], "depth": 2})
    payload = json.loads(out[0].text)
    assert "items" in payload
    assert payload["budget_total"] == 8000

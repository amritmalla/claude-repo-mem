from contextlib import closing
import json
from pathlib import Path

import pytest

from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import connect, init_db
from claude_repo_mem.db.repository import Repository
from claude_repo_mem.indexer.incremental import incremental_reindex
from claude_repo_mem.indexer.orchestrator import full_reindex
from claude_repo_mem.retrieval.trace import trace
from claude_repo_mem.tools.expand import handle as expand
from tests.integration.test_recall_e2e import FakeEmbedder


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "incremental"])
async def test_unicode_source_survives_indexing_expand_and_trace(tmp_repo: Path, mode):
    source = tmp_repo / "café.py"
    before = 'def café(prénom: str) -> str:\n    return "नमस्ते 😀 " + prénom'
    prefix = "# café नेपाली 漢字 😀\n@app.route('/salut')\n"
    source.write_text(prefix + before + "\n", encoding="utf-8")
    settings = Settings.for_repo(tmp_repo)
    init_db(settings.db_path)
    full_reindex(settings, FakeEmbedder())
    with closing(connect(settings.db_path)) as conn:
        before_id = conn.execute("SELECT id FROM unit WHERE kind='function'").fetchone()[0]

    after = before.replace("नमस्ते", "こんにちは")
    source.write_text(prefix + after + "\n", encoding="utf-8")
    if mode == "full":
        full_reindex(settings, FakeEmbedder())
    else:
        incremental_reindex(settings, [source], FakeEmbedder())

    with closing(connect(settings.db_path)) as conn:
        repo = Repository(conn)
        assert repo.get_unit(before_id) is None
        function = next(unit for unit in repo.list_units() if unit.kind == "function")
        route = next(unit for unit in repo.list_units() if unit.kind == "route")
        assert function.t1_header == "python café(prénom: str) -> str"
        assert function.metadata == after
        assert function.source_ref == f"{source.as_posix()}:3-4"
        assert repo.neighbors(route.id, kinds=["route_to"])[0].dst_id == function.id
        assert repo.fts_search("café")

    expanded = await expand(settings, {"handle": function.id, "tier": "T0"})
    assert json.loads(expanded[0].text)["content"] == after
    traced = trace(settings, seeds=[route.id])
    assert next(item.content for item in traced.items if item.handle == function.id) == after

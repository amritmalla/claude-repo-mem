from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import anyio
from click.testing import CliRunner
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CreateMessageResult, TextContent
import numpy as np
import pytest

from claude_repo_mem.cli import main
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import connect, init_db
from claude_repo_mem.db.repository import Repository
from claude_repo_mem.indexer.incremental import incremental_reindex
from claude_repo_mem.indexer.orchestrator import full_reindex
from claude_repo_mem.retrieval.recall import recall
from claude_repo_mem.server import build_server
from claude_repo_mem.units.model import Unit


class Backend:
    def __init__(self, name, dim):
        self.name, self.dim = name, dim
        self.queries = []

    def embed(self, texts):
        self.queries.extend(texts)
        return [np.ones(self.dim, dtype="float32") for _ in texts]


@pytest.fixture
def settings(tmp_repo: Path):
    return Settings.for_repo(tmp_repo)


@pytest.mark.asyncio
async def test_plan_task_uses_live_host_sampling(settings, monkeypatch):
    init_db(settings.db_path)
    monkeypatch.delenv("CLAUDE_REPO_MEM_LLM", raising=False)
    samples = []

    async def sample(context, params):
        samples.append(params)
        assert params.messages[0].content.type == "text"
        assert "token refresh" in params.messages[0].content.text
        assert params.systemPrompt
        return CreateMessageResult(
            role="assistant", model="test-host", stopReason="endTurn",
            content=TextContent(type="text", text=json.dumps({
                "subtasks": [{"title": "Add refresh route", "intent": "Implement refresh", "acceptance": ["Works"]}],
            })),
        )

    with anyio.fail_after(10):
        async with create_connected_server_and_client_session(build_server(settings), sampling_callback=sample) as client:
            result = await client.call_tool("plan_task", {"intent": "Add token refresh"})

    assert not result.isError, result.content
    payload = json.loads(result.content[0].text)
    assert payload["children"][0]["title"] == "Add refresh route"
    assert len(samples) == 1
    with closing(connect(settings.db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM unit WHERE layer='task'").fetchone()[0] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "dim"), [("openai", 1536), ("voyage", 512)])
async def test_server_reuses_selected_embedder_only_for_recall(settings, monkeypatch, name, dim):
    settings = replace(settings, embedder=name)
    init_db(settings.db_path, dim=dim)
    (settings.repo_root / "app.py").write_text("def login(): return 1\n", encoding="utf-8")
    backend = Backend(name, dim)
    full_reindex(settings, backend)
    backend.queries.clear()
    factory = Mock(return_value=backend)
    monkeypatch.setattr("claude_repo_mem.embeddings.factory.make_embedder", factory)
    monkeypatch.setattr(
        "claude_repo_mem.embeddings.bge_small.BgeSmallEmbedder.embed",
        Mock(side_effect=AssertionError("The server used the default backend")),
    )

    with anyio.fail_after(10):
        async with create_connected_server_and_client_session(build_server(settings)) as client:
            result = await client.call_tool("stats", {})
            assert not result.isError
            factory.assert_not_called()
            for _ in range(2):
                result = await client.call_tool("recall", {"query": "login"})
                assert not result.isError, result.content
                assert json.loads(result.content[0].text)["items"]

    factory.assert_called_once_with(name)
    assert backend.queries == ["login", "login"]


@pytest.mark.parametrize("operation", ["recall", "full", "incremental"])
@pytest.mark.parametrize(("name", "dim"), [("other", 384), ("bge-small", 512)])
def test_backend_mismatch_fails_before_embedding(settings, operation, name, dim):
    init_db(settings.db_path)
    source = settings.repo_root / "app.py"
    source.write_text("def login(): return 1\n", encoding="utf-8")
    full_reindex(settings, Backend("bge-small", 384))
    wrong = Backend(name, dim)

    with pytest.raises(ValueError, match="mismatch"):
        if operation == "recall":
            recall(settings, query="login", embedder=wrong)
        elif operation == "full":
            full_reindex(settings, wrong)
        else:
            incremental_reindex(settings, [source], wrong)

    assert wrong.queries == []


@pytest.mark.parametrize(("name", "dim"), [("openai", 1536), ("voyage", 512), ("bge-small", 384)])
def test_generated_config_starts_with_selected_backend(settings, monkeypatch, name, dim):
    runner = CliRunner()
    result = runner.invoke(main, ["init", "--root", str(settings.repo_root), "--embedder", name, "--no-watch"])
    assert result.exit_code == 0, result.output
    assert f"claude-repo-mem index --embedder {name}" in result.output
    entry = json.loads((settings.repo_root / ".mcp.json").read_text())["mcpServers"]["claude-repo-mem"]
    backend = Backend(name, dim)
    monkeypatch.setenv("CLAUDE_REPO_MEM_EMBEDDER", "different-backend")
    factory = Mock(return_value=backend)
    monkeypatch.setattr("claude_repo_mem.embeddings.factory.make_embedder", factory)
    serve = AsyncMock()
    monkeypatch.setattr("claude_repo_mem.server.serve_stdio", serve)

    result = runner.invoke(main, entry["args"])

    assert result.exit_code == 0, result.output
    factory.assert_called_once_with(name)
    assert serve.call_args.kwargs["settings"].embedder == name
    assert serve.call_args.kwargs["embedder"] is backend
    with closing(connect(settings.db_path)) as conn:
        schema = conn.execute("SELECT sql FROM sqlite_master WHERE name='unit_vec'").fetchone()[0]
        assert f"FLOAT[{dim}]" in schema


def test_init_pins_backend_from_environment(settings, monkeypatch):
    monkeypatch.setenv("CLAUDE_REPO_MEM_EMBEDDER", "voyage")
    result = CliRunner().invoke(main, ["init", "--root", str(settings.repo_root)])
    assert result.exit_code == 0, result.output
    args = json.loads((settings.repo_root / ".mcp.json").read_text())["mcpServers"]["claude-repo-mem"]["args"]
    assert args[args.index("--embedder") + 1] == "voyage"
    assert "claude-repo-mem index --embedder voyage" in result.output


def test_first_embedding_run_can_resize_an_empty_vector_index(settings, monkeypatch):
    source = settings.repo_root / "app.py"
    source.write_text("def login(): return 1\n", encoding="utf-8")
    init_db(settings.db_path)
    full_reindex(settings)
    backend = Backend("openai", 1536)
    monkeypatch.setattr("claude_repo_mem.embeddings.factory.make_embedder", Mock(return_value=backend))

    result = CliRunner().invoke(main, ["index", "--root", str(settings.repo_root), "--embedder", "openai"])

    assert result.exit_code == 0, result.output
    assert backend.queries
    with closing(connect(settings.db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM unit_vec").fetchone()[0] == 1
        assert conn.execute("SELECT dim FROM embedder_meta").fetchone()[0] == 1536


def test_no_embed_index_retains_alternative_backend_vectors(settings):
    init_db(settings.db_path, dim=1536)
    (settings.repo_root / "app.py").write_text("def login(): return 1\n", encoding="utf-8")
    full_reindex(settings, Backend("openai", 1536))

    result = CliRunner().invoke(main, ["index", "--root", str(settings.repo_root), "--no-embed"])

    assert result.exit_code == 0, result.output
    with closing(connect(settings.db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM unit_vec").fetchone()[0] == 1
        assert conn.execute("SELECT dim FROM embedder_meta").fetchone()[0] == 1536


@pytest.mark.asyncio
async def test_plan_task_uses_explicit_anthropic_backend(settings, monkeypatch):
    init_db(settings.db_path)
    monkeypatch.setenv("CLAUDE_REPO_MEM_LLM", "anthropic")
    llm = AsyncMock()
    llm.complete.return_value = json.dumps({
        "subtasks": [{"title": "Direct API task", "intent": "Implement", "acceptance": []}],
    })
    factory = Mock(return_value=llm)
    monkeypatch.setattr("claude_repo_mem.llm.anthropic_api.AnthropicApiClient", factory)

    async with create_connected_server_and_client_session(build_server(settings)) as client:
        result = await client.call_tool("plan_task", {"intent": "Implement a feature"})

    assert not result.isError, result.content
    assert json.loads(result.content[0].text)["children"][0]["title"] == "Direct API task"
    factory.assert_called_once_with()
    llm.complete.assert_awaited_once()


def test_init_db_does_not_resize_unlabelled_existing_vectors(settings):
    init_db(settings.db_path)
    with closing(connect(settings.db_path)) as conn:
        Repository(conn).upsert_unit(Unit(
            id="code://function/old", layer="code", kind="function", scope="root",
            source_ref=None, content_hash="old", t1_header="old", created_at=1, last_seen_at=1,
        ), embedding=np.ones(384, dtype="float32"))

    with pytest.raises(ValueError, match="mismatch"):
        init_db(settings.db_path, dim=1536)

    with closing(connect(settings.db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM unit_vec").fetchone()[0] == 1
        assert "FLOAT[384]" in conn.execute("SELECT sql FROM sqlite_master WHERE name='unit_vec'").fetchone()[0]


def test_serve_rejects_backend_mismatch_before_starting(settings, monkeypatch):
    init_db(settings.db_path, dim=1536)
    (settings.repo_root / "app.py").write_text("def login(): return 1\n", encoding="utf-8")
    full_reindex(settings, Backend("openai", 1536))
    monkeypatch.setattr("claude_repo_mem.embeddings.factory.make_embedder", Mock(return_value=Backend("voyage", 512)))
    serve = AsyncMock()
    monkeypatch.setattr("claude_repo_mem.server.serve_stdio", serve)
    watcher = Mock()
    monkeypatch.setattr("claude_repo_mem.watcher.fs_watcher.FileWatcher", watcher)

    result = CliRunner().invoke(main, ["serve", "--root", str(settings.repo_root), "--embedder", "voyage"])

    assert result.exit_code != 0
    assert "mismatch" in result.output
    serve.assert_not_called()
    watcher.assert_not_called()
    with closing(connect(settings.db_path)) as conn:
        assert conn.execute("SELECT name, dim FROM embedder_meta").fetchone()["name"] == "openai"
        assert conn.execute("SELECT COUNT(*) FROM unit_vec").fetchone()[0] == 1

from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock

from click.testing import CliRunner
import pytest

from claude_repo_mem.cli import main
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import connect, init_db
from claude_repo_mem.db.repository import Repository
from claude_repo_mem.indexer.incremental import incremental_reindex
from claude_repo_mem.indexer.orchestrator import full_reindex
from claude_repo_mem.queue.background import BackgroundQueue
from claude_repo_mem.summarizer.backfill import backfill_summaries
from claude_repo_mem.watcher.fs_watcher import FileWatcher
from tests.integration.test_recall_e2e import FakeEmbedder


@pytest.fixture
def indexed(tmp_repo: Path):
    source = tmp_repo / "app.py"
    source.write_text(
        "def retained():\n"
        "    # This function is long enough to receive a generated summary during backfill.\n"
        "    return 1\n\n"
        "def changed():\n    return 2\n",
        encoding="utf-8",
    )
    (tmp_repo / "guide.md").write_text("# Guide\n\nKeep this documentation.\n", encoding="utf-8")
    settings = Settings.for_repo(tmp_repo)
    init_db(settings.db_path)
    full_reindex(settings, FakeEmbedder())
    return settings, source


def _vectors(settings):
    with closing(connect(settings.db_path)) as conn:
        return dict(conn.execute("SELECT id, embedding FROM unit_vec").fetchall())


def test_incremental_without_embedding_preserves_existing_vectors(indexed):
    settings, source = indexed
    before = _vectors(settings)
    source.write_text(source.read_text(encoding="utf-8") + "\ndef added(): pass\n", encoding="utf-8")

    incremental_reindex(settings, [source])

    assert _vectors(settings) == before
    with closing(connect(settings.db_path)) as conn:
        assert Repository(conn).fts_search("added")
        assert conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0] == len(before) + 1


def test_incremental_drops_only_obsolete_vectors(indexed):
    settings, source = indexed
    before = _vectors(settings)
    with closing(connect(settings.db_path)) as conn:
        old_id = Repository(conn).fts_search("changed")[0].id
    source.write_text(
        source.read_text(encoding="utf-8").replace("return 2", "return 3"), encoding="utf-8",
    )

    incremental_reindex(settings, [source])

    assert _vectors(settings) == {uid: vector for uid, vector in before.items() if uid != old_id}
    with closing(connect(settings.db_path)) as conn:
        repo = Repository(conn)
        assert repo.get_unit(old_id) is None
        assert repo.fts_search("changed")[0].id != old_id


def test_no_embed_cli_preserves_vectors_for_unchanged_content(indexed):
    settings, _ = indexed
    before = _vectors(settings)

    result = CliRunner().invoke(main, ["index", "--root", str(settings.repo_root), "--no-embed"])

    assert result.exit_code == 0, result.output
    assert _vectors(settings) == before


@pytest.mark.asyncio
async def test_summary_backfill_preserves_vectors(indexed):
    settings, _ = indexed
    before = _vectors(settings)
    llm = AsyncMock()
    llm.complete.return_value = "Generated summary"

    stats = await backfill_summaries(settings, llm=llm)

    assert stats["units_summarized"] > 0
    assert _vectors(settings) == before
    with closing(connect(settings.db_path)) as conn:
        assert Repository(conn).fts_search("Generated")


def test_default_watcher_job_preserves_existing_vectors(indexed):
    settings, source = indexed
    before = _vectors(settings)
    source.write_text(source.read_text(encoding="utf-8") + "\ndef added(): pass\n", encoding="utf-8")
    queue = BackgroundQueue()
    watcher = FileWatcher(settings, queue=queue)
    queue.start()
    try:
        watcher._on_flush([source])
        queue.drain(timeout=5)
    finally:
        queue.stop()

    with closing(connect(settings.db_path)) as conn:
        assert Repository(conn).fts_search("added")
    assert _vectors(settings) == before

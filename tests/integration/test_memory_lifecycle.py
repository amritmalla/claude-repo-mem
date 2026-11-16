from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import connect, init_db
from claude_repo_mem.db.repository import Repository
from claude_repo_mem.indexer.incremental import incremental_reindex
from claude_repo_mem.indexer.orchestrator import full_reindex
from claude_repo_mem.indexer.parsers.memory_md import MemoryMarkdownParser
from claude_repo_mem.memory.writer import TOMBSTONE_HANDLE, forget, remember
from claude_repo_mem.retrieval.recall import recall
from tests.integration.test_recall_e2e import FakeEmbedder


@pytest.fixture
def settings(tmp_repo: Path):
    settings = Settings.for_repo(tmp_repo)
    init_db(settings.db_path)
    return settings


def _refresh(settings, paths, mode, fresh=False):
    if fresh:
        settings = replace(settings, db_path=settings.state_dir / "rebuilt.sqlite")
        init_db(settings.db_path)
    if mode == "full":
        full_reindex(settings)
    else:
        incremental_reindex(settings, paths)
    return settings


def _active_handles(settings, include_superseded=False):
    result = recall(
        settings, query="memory", embedder=FakeEmbedder(), layers=["memory"],
        include_superseded=include_superseded,
    )
    return {item.handle for item in result.items}


@pytest.mark.parametrize("mode", ["full", "incremental"])
@pytest.mark.parametrize("fresh", [False, True], ids=["existing-db", "fresh-db"])
def test_forgotten_memory_stays_inactive_after_reindex(settings, mode, fresh):
    forgotten = remember(settings, fact="Obsolete memory", scope="auth")
    current = remember(settings, fact="Current memory", scope="auth")
    forget(settings, handle=forgotten.handle)

    refreshed = _refresh(settings, [forgotten.path, current.path], mode, fresh)
    # Repeating indexing must also preserve the lifecycle state.
    _refresh(refreshed, [forgotten.path, current.path], mode)

    with closing(connect(refreshed.db_path)) as conn:
        repo = Repository(conn)
        assert repo.get_unit(forgotten.handle).superseded_by == TOMBSTONE_HANDLE
        assert repo.get_unit(current.handle).superseded_by is None
        assert repo.get_unit(TOMBSTONE_HANDLE).superseded_by is not None
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert _active_handles(refreshed) == {current.handle}
    assert forgotten.handle in _active_handles(refreshed, include_superseded=True)


@pytest.mark.parametrize("mode", ["full", "incremental"])
@pytest.mark.parametrize("fresh", [False, True], ids=["existing-db", "fresh-db"])
def test_supersession_restored_independent_of_file_order(settings, monkeypatch, mode, fresh):
    old = remember(settings, fact="Old memory", scope="auth")
    current = remember(settings, fact="Current memory", scope="auth", supersedes=old.handle)
    paths = [current.path, old.path]
    if mode == "full":
        monkeypatch.setattr(
            "claude_repo_mem.indexer.orchestrator.walk_repo", lambda root, **kwargs: iter(paths),
        )

    refreshed = _refresh(settings, paths, mode, fresh)

    with closing(connect(refreshed.db_path)) as conn:
        repo = Repository(conn)
        assert repo.get_unit(old.handle).superseded_by == current.handle
        assert repo.get_unit(current.handle).superseded_by is None
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert _active_handles(refreshed) == {current.handle}


def test_incremental_old_memory_alone_keeps_supersession(settings):
    old = remember(settings, fact="Old memory", scope="auth")
    current = remember(settings, fact="Current memory", scope="auth", supersedes=old.handle)

    incremental_reindex(settings, [old.path])

    assert _active_handles(settings) == {current.handle}


@pytest.mark.parametrize("mode", ["full", "incremental"])
def test_editing_forgotten_memory_does_not_reactivate_it(settings, mode):
    forgotten = remember(settings, fact="Obsolete memory", scope="auth")
    forget(settings, handle=forgotten.handle)
    text = forgotten.path.read_text(encoding="utf-8").replace("Obsolete memory", "Edited memory")
    forgotten.path.write_text(text, encoding="utf-8")

    _refresh(settings, [forgotten.path], mode)

    assert _active_handles(settings) == set()


@pytest.mark.parametrize("initial", ["body-marker", "false-flag", "no-frontmatter"])
def test_forget_persists_actual_frontmatter_marker(settings, initial):
    memory = remember(settings, fact="Memory mentioning tombstoned: true", scope="auth")
    if initial == "false-flag":
        text = memory.path.read_text(encoding="utf-8")
        memory.path.write_text(text.replace("---\n", "---\ntombstoned: false\n", 1), encoding="utf-8")
    elif initial == "no-frontmatter":
        memory.path.write_text("Memory mentioning tombstoned: true\n", encoding="utf-8")

    forget(settings, handle=memory.handle)
    first = memory.path.read_text(encoding="utf-8")
    forget(settings, handle=memory.handle)

    assert memory.path.read_text(encoding="utf-8") == first
    assert yaml.safe_load(first.split("---", 2)[1])["tombstoned"] is True
    assert "Memory mentioning tombstoned: true" in first
    parsed = MemoryMarkdownParser().parse(memory.path, first).units[0]
    assert parsed.superseded_by == TOMBSTONE_HANDLE


def test_forgetting_a_replacement_does_not_reactivate_old_memory(settings):
    old = remember(settings, fact="Old memory", scope="auth")
    replacement = remember(settings, fact="Replacement memory", scope="auth", supersedes=old.handle)
    forget(settings, handle=replacement.handle)

    refreshed = _refresh(settings, [replacement.path, old.path], "full", fresh=True)

    assert _active_handles(refreshed) == set()

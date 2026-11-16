from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path

import pytest

from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import connect, init_db
from claude_repo_mem.db.repository import Repository
from claude_repo_mem.handoff.snapshot import handoff
from claude_repo_mem.indexer.orchestrator import full_reindex
from claude_repo_mem.memory.writer import remember
from claude_repo_mem.units.model import Relation, Unit
from tests.integration.test_recall_e2e import FakeEmbedder


@pytest.fixture
def settings(tmp_repo: Path):
    result = Settings.for_repo(tmp_repo)
    init_db(result.db_path)
    return result


@pytest.mark.parametrize(("name", "before", "after"), [
    ("app.py", "def legacy(): return 1\n", "def legacy(): return 2\n"),
    ("app.py", "def legacy(): return 1\n", "def current(): return 1\n"),
    ("app.py", "class Worker:\n    def run(self): return 1\n",
     "class Worker:\n    def run(self): return 2\n"),
    ("guide.md", "# Legacy\n\nOld content\n", "# Current\n\nNew content\n"),
    ("guide.md", "---\nversion: 1\n---\n# Guide\n\nContent\n",
     "---\nversion: 2\n---\n# Guide\n\nContent\n"),
])
def test_full_reindex_replaces_edited_units(settings, name, before, after):
    path = settings.repo_root / name
    path.write_text(before, encoding="utf-8")
    embedder = FakeEmbedder()
    full_reindex(settings, embedder)
    with closing(connect(settings.db_path)) as conn:
        old_ids = {row[0] for row in conn.execute("SELECT id FROM unit")}

    path.write_text(after, encoding="utf-8")
    stats = full_reindex(settings, embedder)

    with closing(connect(settings.db_path)) as conn:
        current_ids = {row[0] for row in conn.execute("SELECT id FROM unit")}
        assert current_ids - old_ids
        assert len(current_ids) == stats["units_written"]
        assert {row[0] for row in conn.execute("SELECT id FROM unit_fts")} == current_ids
        assert {row[0] for row in conn.execute("SELECT id FROM unit_vec")} == current_ids
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("change", ["delete", "rename", "empty", "unsupported", "ignored"])
def test_full_reindex_removes_units_for_missing_content(settings, change):
    path = settings.repo_root / "app.py"
    path.write_text("class Legacy:\n    def run(self): return 1\n", encoding="utf-8")
    embedder = FakeEmbedder()
    full_reindex(settings, embedder)
    with closing(connect(settings.db_path)) as conn:
        old_ids = {row[0] for row in conn.execute("SELECT id FROM unit")}

    if change == "delete":
        path.unlink()
    elif change == "rename":
        path.rename(path.with_name("renamed.py"))
    elif change == "empty":
        path.write_text("", encoding="utf-8")
    elif change == "unsupported":
        path.rename(path.with_suffix(".txt"))
    else:
        ignored = settings.repo_root / "build"
        ignored.mkdir()
        path.rename(ignored / path.name)

    stats = full_reindex(settings, embedder)

    with closing(connect(settings.db_path)) as conn:
        current_ids = {row[0] for row in conn.execute("SELECT id FROM unit")}
        assert not old_ids & current_ids
        assert len(current_ids) == stats["units_written"]
        assert {row[0] for row in conn.execute("SELECT id FROM unit_fts")} == current_ids
        assert {row[0] for row in conn.execute("SELECT id FROM unit_vec")} == current_ids
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_full_reindex_preserves_memories_tasks_and_snapshots(settings):
    source = settings.repo_root / "app.py"
    source.write_text("def legacy(): pass\n", encoding="utf-8")
    full_reindex(settings)
    memory = remember(settings, fact="Use JWT", scope="auth")
    memory_text = memory.path.read_text(encoding="utf-8")
    with closing(connect(settings.db_path)) as conn:
        repo = Repository(conn)
        code_id = conn.execute("SELECT id FROM unit WHERE layer='code'").fetchone()[0]
        task = Unit(
            id="task://task/keep", layer="task", kind="task", scope="auth",
            source_ref=None, content_hash="task", t1_header="Keep this task",
            created_at=1, last_seen_at=1, parent_id=code_id,
            metadata=json.dumps({"title": "Keep this task", "context_handles": [code_id]}),
        )
        repo.upsert_unit(task)
    snapshot = handoff(settings, task_id=task.id)
    snapshot_text = snapshot.markdown_path.read_text(encoding="utf-8")
    source.unlink()

    full_reindex(settings)

    with closing(connect(settings.db_path)) as conn:
        repo = Repository(conn)
        assert repo.get_unit(code_id) is None
        assert repo.get_unit(memory.handle) is not None
        assert repo.get_unit(task.id) == replace(task, parent_id=None)
        assert repo.get_unit(snapshot.snapshot_handle).parent_id == task.id
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert memory.path.read_text(encoding="utf-8") == memory_text
    assert snapshot.markdown_path.read_text(encoding="utf-8") == snapshot_text


def test_full_reindex_refreshes_import_edges_with_unchanged_handles(settings):
    caller = settings.repo_root / "caller.py"
    caller.write_text("from old import target\ndef caller(): return target()\n", encoding="utf-8")
    for module in ("old", "current"):
        (settings.repo_root / f"{module}.py").write_text("def target(): pass\n", encoding="utf-8")
    full_reindex(settings)
    memory = remember(settings, fact="Keep this relationship", scope="root")
    with closing(connect(settings.db_path)) as conn:
        caller_id = conn.execute(
            "SELECT id FROM unit WHERE t1_header = 'python caller()'",
        ).fetchone()[0]
        Repository(conn).add_relation(Relation(memory.handle, caller_id, "mentions"))

    caller.write_text("from current import target\ndef caller(): return target()\n", encoding="utf-8")
    full_reindex(settings)

    with closing(connect(settings.db_path)) as conn:
        targets = conn.execute(
            "SELECT u.source_ref FROM relation r JOIN unit u ON u.id = r.dst_id "
            "WHERE r.src_id = ? AND r.kind = 'imports'", (caller_id,),
        ).fetchall()
        assert len(targets) == 1
        assert targets[0][0].startswith((settings.repo_root / "current.py").as_posix() + ":")
        assert Repository(conn).neighbors(memory.handle) == [
            Relation(memory.handle, caller_id, "mentions"),
        ]


def _snapshot(settings):
    with closing(connect(settings.db_path)) as conn:
        return {
            table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]
            for table in ("unit", "unit_fts", "unit_vec", "relation", "embedder_meta")
        }


@pytest.mark.parametrize("failure", ["read", "directory", "embedding", "write"])
def test_failed_full_reindex_keeps_previous_snapshot(settings, monkeypatch, failure):
    directory = settings.repo_root / "src"
    directory.mkdir()
    source = directory / "app.py"
    source.write_text("@app.route('/old')\ndef route(): return 1\n", encoding="utf-8")
    embedder = FakeEmbedder()
    full_reindex(settings, embedder)
    before = _snapshot(settings)
    source.write_text("@app.route('/current')\ndef route(): return 2\n", encoding="utf-8")

    if failure == "read":
        original_read = Path.read_text

        def fail_read(path, *args, **kwargs):
            if path == source:
                raise PermissionError("cannot read source")
            return original_read(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", fail_read)
    elif failure == "directory":
        original_iterdir = Path.iterdir

        def fail_iterdir(path):
            if path == directory:
                raise PermissionError("cannot scan directory")
            return original_iterdir(path)

        monkeypatch.setattr(Path, "iterdir", fail_iterdir)
    elif failure == "embedding":
        def fail_embed(texts):
            raise RuntimeError("embedding failed")

        monkeypatch.setattr(embedder, "embed", fail_embed)
    else:
        original_add = Repository.add_relation

        def fail_write(repo, relation):
            original_add(repo, relation)
            raise RuntimeError("write failed")

        monkeypatch.setattr(Repository, "add_relation", fail_write)

    with pytest.raises((OSError, ValueError, RuntimeError)):
        full_reindex(settings, embedder)

    assert _snapshot(settings) == before

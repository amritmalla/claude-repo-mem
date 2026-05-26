from pathlib import Path
import pytest
from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db, connect
from claude_repo_mem.indexer.orchestrator import full_reindex
from claude_repo_mem.indexer.incremental import incremental_reindex


@pytest.fixture
def indexed(tmp_repo: Path):
    (tmp_repo / "a.py").write_text("def f(): pass\n")
    (tmp_repo / "b.py").write_text("def g(): pass\n")
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=None)
    return s, tmp_repo


def test_incremental_picks_up_new_function(indexed):
    s, root = indexed
    p = root / "a.py"
    p.write_text("def f(): pass\ndef newly_added(): pass\n")
    stats = incremental_reindex(s, [p], embedder=None)
    assert stats["files_processed"] == 1
    conn = connect(s.db_path)
    names = [r["t1_header"] for r in conn.execute(
        "SELECT t1_header FROM unit WHERE source_ref LIKE ? AND layer='code'",
        ("%a.py%",),
    ).fetchall()]
    assert any("newly_added" in n for n in names)


def test_incremental_does_not_touch_other_files(indexed):
    s, root = indexed
    p = root / "a.py"
    p.write_text("def replaced(): pass\n")
    conn = connect(s.db_path)
    before = conn.execute(
        "SELECT COUNT(*) FROM unit WHERE layer='code' AND source_ref LIKE ?",
        ("%b.py%",),
    ).fetchone()[0]
    incremental_reindex(s, [p], embedder=None)
    after = conn.execute(
        "SELECT COUNT(*) FROM unit WHERE layer='code' AND source_ref LIKE ?",
        ("%b.py%",),
    ).fetchone()[0]
    assert before == after


def test_incremental_handles_deleted_file(indexed):
    s, root = indexed
    p = root / "a.py"
    p.unlink()
    incremental_reindex(s, [p], embedder=None)
    conn = connect(s.db_path)
    n = conn.execute(
        "SELECT COUNT(*) FROM unit WHERE source_ref LIKE ?",
        ("%a.py%",),
    ).fetchone()[0]
    assert n == 0


def test_incremental_returns_stats(indexed):
    s, root = indexed
    stats = incremental_reindex(s, [root / "a.py"], embedder=None)
    assert "files_processed" in stats
    assert "units_touched" in stats

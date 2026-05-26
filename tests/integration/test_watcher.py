import time
from pathlib import Path
import pytest

from claude_repo_mem.config import Settings
from claude_repo_mem.db.connection import init_db, connect
from claude_repo_mem.indexer.orchestrator import full_reindex
from claude_repo_mem.watcher.fs_watcher import FileWatcher


pytestmark = pytest.mark.slow


def test_watcher_reindexes_new_function_after_quiet(tmp_repo: Path):
    (tmp_repo / "a.py").write_text("def f(): pass\n")
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=None)

    w = FileWatcher(s, embedder=None, quiet_ms=200)
    w.start()
    try:
        (tmp_repo / "a.py").write_text("def f(): pass\ndef freshly_added(): pass\n")
        deadline = time.monotonic() + 5.0
        seen = False
        while time.monotonic() < deadline:
            conn = connect(s.db_path)
            rows = conn.execute(
                "SELECT t1_header FROM unit WHERE source_ref LIKE ? AND layer='code'",
                ("%a.py%",),
            ).fetchall()
            if any("freshly_added" in r["t1_header"] for r in rows):
                seen = True
                break
            time.sleep(0.1)
        assert seen, "watcher did not pick up the new function within 5s"
    finally:
        w.stop()


def test_watcher_picks_up_deleted_file(tmp_repo: Path):
    (tmp_repo / "a.py").write_text("def f(): pass\n")
    s = Settings.for_repo(tmp_repo)
    init_db(s.db_path)
    full_reindex(s, embedder=None)

    w = FileWatcher(s, embedder=None, quiet_ms=200)
    w.start()
    try:
        (tmp_repo / "a.py").unlink()
        deadline = time.monotonic() + 5.0
        gone = False
        while time.monotonic() < deadline:
            conn = connect(s.db_path)
            n = conn.execute(
                "SELECT COUNT(*) FROM unit WHERE source_ref LIKE ?",
                ("%a.py%",),
            ).fetchone()[0]
            if n == 0:
                gone = True
                break
            time.sleep(0.1)
        assert gone
    finally:
        w.stop()

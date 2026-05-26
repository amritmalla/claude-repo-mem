from pathlib import Path
from claude_repo_mem.db.connection import connect, init_db


def test_init_db_creates_file_and_tables(db_path: Path):
    init_db(db_path)
    assert db_path.exists()
    conn = connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','virtual_table')")}
    assert "unit" in tables
    assert "relation" in tables
    assert "unit_fts" in tables
    assert "unit_vec" in tables


def test_init_db_idempotent(db_path: Path):
    init_db(db_path)
    init_db(db_path)  # second call must not error
    conn = connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM unit").fetchone()[0]
    assert n == 0


def test_vec_extension_loaded(db_path: Path):
    init_db(db_path)
    conn = connect(db_path)
    # vec_version() comes from sqlite-vec
    version = conn.execute("SELECT vec_version()").fetchone()[0]
    assert version  # truthy

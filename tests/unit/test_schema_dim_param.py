from pathlib import Path
from claude_mem.db.connection import init_db, connect


def test_init_db_default_creates_meta_table(tmp_path: Path):
    db = tmp_path / "x.sqlite"
    init_db(db)
    conn = connect(db)
    # Insert a meta row to confirm table+columns exist.
    conn.execute(
        "INSERT INTO embedder_meta(name, dim, created_at) VALUES(?, ?, ?)",
        ("bge-small", 384, 0),
    )
    row = conn.execute("SELECT name, dim FROM embedder_meta").fetchone()
    assert row["name"] == "bge-small"
    assert row["dim"] == 384


def test_init_db_custom_dim_512(tmp_path: Path):
    db = tmp_path / "x.sqlite"
    init_db(db, dim=512)
    # Smoke: inserting a 512-dim vector via vec0 works only on the right schema.
    # We don't insert here (sqlite-vec requires a packed blob); we just confirm
    # the table exists and is usable for SELECT.
    conn = connect(db)
    rows = conn.execute("SELECT count(*) FROM unit_vec").fetchone()
    assert rows[0] == 0

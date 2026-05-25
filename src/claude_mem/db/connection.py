from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec

from .schema import DDL


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with sqlite-vec loaded and foreign keys on."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    """Create the DB and run DDL. Idempotent."""
    conn = connect(db_path)
    try:
        for stmt in DDL:
            conn.execute(stmt)
        conn.commit()
    finally:
        conn.close()

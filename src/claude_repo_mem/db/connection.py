from __future__ import annotations

import sqlite3
import re
from pathlib import Path

import sqlite_vec

from .schema import ddl


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


def vector_dimension(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE name='unit_vec'").fetchone()
    if row is None:
        return None
    match = re.search(r"FLOAT\s*\[\s*(\d+)\s*\]", row[0], re.IGNORECASE)
    if match is None:
        raise ValueError("Cannot determine index vector dimension")
    return int(match.group(1))


def init_db(db_path: Path, dim: int | None = None) -> None:
    """Initialize schema, preserving existing width unless explicitly selected.

    An empty lexical-only vector table can adopt its first embedding backend.
    Existing embedded indexes require an explicit reset to change dimensions.
    """
    conn = connect(db_path)
    try:
        conn.execute("SAVEPOINT initialize_schema")
        existing_dim = vector_dimension(conn)
        selected_dim = dim if dim is not None else (existing_dim or 384)
        if existing_dim is not None and existing_dim != selected_dim:
            meta_exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='embedder_meta'").fetchone()
            has_meta = meta_exists and conn.execute("SELECT 1 FROM embedder_meta LIMIT 1").fetchone()
            has_vectors = conn.execute("SELECT 1 FROM unit_vec LIMIT 1").fetchone()
            if has_meta or has_vectors:
                raise ValueError(
                    f"embedding dimension mismatch: db has {existing_dim}, got {selected_dim}. "
                    "Run `claude-repo-mem index --reset` to change backends."
                )
            conn.execute("DROP TABLE unit_vec")
        for stmt in ddl(selected_dim):
            conn.execute(stmt)
        conn.execute("RELEASE SAVEPOINT initialize_schema")
    finally:
        conn.close()

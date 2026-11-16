"""Validate vector space compatibility before embedding requests or writes."""
from __future__ import annotations

import sqlite3

from ..db.connection import vector_dimension
from .base import Embedder


def validate_embedder(conn: sqlite3.Connection, embedder: Embedder) -> None:
    name = getattr(embedder, "name", "unknown")
    row = conn.execute("SELECT name, dim FROM embedder_meta LIMIT 1").fetchone()
    if row and (row["name"] != name or row["dim"] != embedder.dim):
        raise ValueError(
            f"embedder mismatch: db has {row['name']}/{row['dim']}, got {name}/{embedder.dim}. "
            "Use the indexed backend, or run `claude-repo-mem index --reset` to switch."
        )
    dim = vector_dimension(conn)
    if dim is not None and dim != embedder.dim:
        raise ValueError(
            f"embedding dimension mismatch: db has {dim}, got {embedder.dim}. "
            "Run `claude-repo-mem index --embedder <name>` to build a matching index."
        )

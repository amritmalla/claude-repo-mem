from __future__ import annotations

import sqlite3
import struct
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

import numpy as np

from ..units.model import Unit, Relation


@dataclass(frozen=True)
class SearchHit:
    id: str
    rank: int           # 1-based rank in this result set
    score: float        # backend-specific (bm25 or distance)


def _serialize_embedding(vec: np.ndarray) -> bytes:
    arr = np.asarray(vec, dtype="float32")
    if arr.shape != (384,):
        raise ValueError(f"embedding must be shape (384,), got {arr.shape}")
    return arr.tobytes()


class Repository:
    """The only module that writes SQL outside of schema."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # -- units --------------------------------------------------------------

    def upsert_unit(self, u: Unit, embedding: Optional[np.ndarray] = None) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO unit (id, layer, kind, scope, source_ref, content_hash,
                                  t1_header, t2_summary, parent_id, superseded_by,
                                  confidence, created_at, last_seen_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    layer=excluded.layer,
                    kind=excluded.kind,
                    scope=excluded.scope,
                    source_ref=excluded.source_ref,
                    content_hash=excluded.content_hash,
                    t1_header=excluded.t1_header,
                    t2_summary=excluded.t2_summary,
                    parent_id=excluded.parent_id,
                    superseded_by=excluded.superseded_by,
                    confidence=excluded.confidence,
                    last_seen_at=excluded.last_seen_at,
                    metadata=excluded.metadata
                """,
                (
                    u.id, u.layer, u.kind, u.scope, u.source_ref, u.content_hash,
                    u.t1_header, u.t2_summary, u.parent_id, u.superseded_by,
                    u.confidence, u.created_at, u.last_seen_at, u.metadata,
                ),
            )
            # FTS mirror.
            self.conn.execute("DELETE FROM unit_fts WHERE id = ?", (u.id,))
            self.conn.execute(
                "INSERT INTO unit_fts(id, t1_header, t2_summary) VALUES (?, ?, ?)",
                (u.id, u.t1_header, u.t2_summary or ""),
            )
            # Vector mirror.
            self.conn.execute("DELETE FROM unit_vec WHERE id = ?", (u.id,))
            if embedding is not None:
                self.conn.execute(
                    "INSERT INTO unit_vec(id, embedding) VALUES (?, ?)",
                    (u.id, _serialize_embedding(embedding)),
                )

    def get_unit(self, unit_id: str) -> Optional[Unit]:
        row = self.conn.execute("SELECT * FROM unit WHERE id = ?", (unit_id,)).fetchone()
        if not row:
            return None
        return _row_to_unit(row)

    def get_units(self, ids: Sequence[str]) -> List[Unit]:
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT * FROM unit WHERE id IN ({placeholders})", tuple(ids)
        ).fetchall()
        by_id = {r["id"]: _row_to_unit(r) for r in rows}
        return [by_id[i] for i in ids if i in by_id]

    def delete_unit(self, unit_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM unit_fts WHERE id = ?", (unit_id,))
            self.conn.execute("DELETE FROM unit_vec WHERE id = ?", (unit_id,))
            self.conn.execute("DELETE FROM unit WHERE id = ?", (unit_id,))

    # -- search -------------------------------------------------------------

    def fts_search(self, query: str, limit: int = 50) -> List[SearchHit]:
        # FTS5 'bm25(table)' returns a score where lower = better. We invert.
        rows = self.conn.execute(
            """
            SELECT id, bm25(unit_fts) AS s
            FROM unit_fts
            WHERE unit_fts MATCH ?
            ORDER BY s ASC
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return [SearchHit(id=r["id"], rank=i + 1, score=-r["s"]) for i, r in enumerate(rows)]

    def vec_search(self, embedding: np.ndarray, limit: int = 50) -> List[SearchHit]:
        rows = self.conn.execute(
            """
            SELECT id, distance
            FROM unit_vec
            WHERE embedding MATCH ?
            ORDER BY distance ASC
            LIMIT ?
            """,
            (_serialize_embedding(embedding), limit),
        ).fetchall()
        return [SearchHit(id=r["id"], rank=i + 1, score=-r["distance"]) for i, r in enumerate(rows)]

    # -- relations ----------------------------------------------------------

    def add_relation(self, r: Relation) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO relation(src_id, dst_id, kind) VALUES (?, ?, ?)",
                (r.src_id, r.dst_id, r.kind),
            )

    def neighbors(
        self,
        unit_id: str,
        direction: str = "out",
        kinds: Optional[Sequence[str]] = None,
    ) -> List[Relation]:
        if direction == "out":
            sql = "SELECT src_id, dst_id, kind FROM relation WHERE src_id = ?"
        elif direction == "in":
            sql = "SELECT src_id, dst_id, kind FROM relation WHERE dst_id = ?"
        else:
            raise ValueError(f"direction must be 'in' or 'out', got {direction!r}")
        params: list = [unit_id]
        if kinds:
            sql += f" AND kind IN ({','.join('?' * len(kinds))})"
            params.extend(kinds)
        rows = self.conn.execute(sql, params).fetchall()
        return [Relation(r["src_id"], r["dst_id"], r["kind"]) for r in rows]


def _row_to_unit(row: sqlite3.Row) -> Unit:
    return Unit(
        id=row["id"],
        layer=row["layer"],
        kind=row["kind"],
        scope=row["scope"],
        source_ref=row["source_ref"],
        content_hash=row["content_hash"],
        t1_header=row["t1_header"],
        t2_summary=row["t2_summary"],
        parent_id=row["parent_id"],
        superseded_by=row["superseded_by"],
        confidence=row["confidence"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
        metadata=row["metadata"],
    )

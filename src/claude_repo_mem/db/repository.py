from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional, Sequence
from uuid import uuid4

import numpy as np

from ..units.model import Unit, Relation


@dataclass(frozen=True)
class SearchHit:
    id: str
    rank: int           # 1-based rank in this result set
    score: float        # backend-specific (bm25 or distance)


def _serialize_embedding(vec: np.ndarray) -> bytes:
    arr = np.asarray(vec, dtype="float32")
    if arr.ndim != 1:
        raise ValueError(f"embedding must be 1-D, got shape {arr.shape}")
    return arr.tobytes()


class Repository:
    """The only module that writes SQL outside of schema."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Group writes atomically, including calls to other repository methods."""
        savepoint = f"repo_{uuid4().hex}"
        self.conn.execute(f"SAVEPOINT {savepoint}")
        try:
            yield
        except BaseException:
            self.conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise
        else:
            self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")

    # -- units --------------------------------------------------------------

    def upsert_unit(self, u: Unit, embedding: Optional[np.ndarray] = None) -> None:
        """Update a unit, preserving its vector when its content/header match.

        A supplied vector replaces the old one. Without one, content or header
        changes invalidate the old vector until embeddings are regenerated.
        """
        with self.transaction():
            previous = self.conn.execute(
                "SELECT content_hash, t1_header FROM unit WHERE id = ?", (u.id,),
            ).fetchone()
            content_changed = (
                previous is None
                or previous["content_hash"] != u.content_hash
                or previous["t1_header"] != u.t1_header
            )
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
            # Metadata-only updates must not erase an existing embedding.
            if embedding is not None or content_changed:
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

    def list_units(self) -> List[Unit]:
        return [_row_to_unit(row) for row in self.conn.execute("SELECT * FROM unit")]

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
        self.delete_units([unit_id])

    def delete_units(self, unit_ids: Iterable[str]) -> int:
        """Remove units and search entries, detaching references from survivors."""
        with self.transaction():
            self.conn.execute("CREATE TEMP TABLE deleted_unit_ids (id TEXT PRIMARY KEY)")
            self.conn.executemany(
                "INSERT OR IGNORE INTO deleted_unit_ids(id) VALUES (?)",
                ((uid,) for uid in unit_ids),
            )
            ids = "SELECT id FROM deleted_unit_ids"
            count = self.conn.execute(f"SELECT COUNT(*) FROM unit WHERE id IN ({ids})").fetchone()[0]
            self.conn.execute(f"UPDATE unit SET parent_id = NULL WHERE parent_id IN ({ids})")
            self.conn.execute(f"UPDATE unit SET superseded_by = NULL WHERE superseded_by IN ({ids})")
            self.conn.execute(f"DELETE FROM unit_fts WHERE id IN ({ids})")
            self.conn.execute(f"DELETE FROM unit_vec WHERE id IN ({ids})")
            self.conn.execute(f"DELETE FROM unit WHERE id IN ({ids})")
            self.conn.execute("DROP TABLE deleted_unit_ids")
        return count

    def prune_indexed_units(self, current_ids: Iterable[str]) -> int:
        """Prune obsolete code/docs and reset their graph for a full refresh.

        Durable memory/task units and cross-layer edges between surviving units
        remain. References to removed units are detached to preserve valid FKs.
        A temporary ID table avoids SQLite parameter limits on large indexes.
        """
        with self.transaction():
            self.conn.execute("CREATE TEMP TABLE reindex_current (id TEXT PRIMARY KEY)")
            self.conn.executemany(
                "INSERT OR IGNORE INTO reindex_current(id) VALUES (?)",
                ((uid,) for uid in current_ids),
            )
            stale_ids = (
                "SELECT id FROM unit WHERE layer IN ('code','docs') "
                "AND id NOT IN (SELECT id FROM reindex_current)"
            )
            self.conn.execute(
                "DELETE FROM relation "
                "WHERE src_id IN (SELECT id FROM unit WHERE layer IN ('code','docs')) "
                "AND dst_id IN (SELECT id FROM unit WHERE layer IN ('code','docs'))"
            )
            count = self.delete_units(row[0] for row in self.conn.execute(stale_ids))
            self.conn.execute("DROP TABLE reindex_current")
        return count

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
        with self.transaction():
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

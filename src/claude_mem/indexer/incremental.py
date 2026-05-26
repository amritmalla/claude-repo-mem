from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository
from ..embeddings.base import Embedder
from .orchestrator import _pick_parser, _relativize_scope


def incremental_reindex(
    settings: Settings,
    paths: Iterable[Path],
    embedder: Optional[Embedder] = None,
) -> dict:
    """Re-parse only the given paths and upsert their units. Delete units whose
    `source_ref` matches a path that no longer exists or whose ID is no longer
    produced by the parser for that path.
    """
    conn = connect(settings.db_path)
    repo = Repository(conn)
    repo_root = settings.repo_root
    files_processed = 0
    new_unit_ids: set[str] = set()

    for path in paths:
        files_processed += 1
        path_posix = path.as_posix()
        # Source refs may include `:line-range` suffixes (from code parsers).
        # Match both exact and prefix-with-colon.
        existing_ids = {
            r["id"] for r in conn.execute(
                "SELECT id FROM unit WHERE source_ref = ? OR source_ref LIKE ?",
                (path_posix, path_posix + ":%"),
            ).fetchall()
        }

        if not path.exists():
            for uid in existing_ids:
                _delete_unit(conn, uid)
            conn.commit()
            continue

        parser = _pick_parser(path)
        if parser is None:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        result = parser.parse(path, text)
        produced_ids: set[str] = set()
        new_units = [_relativize_scope(u, repo_root) for u in result.units]
        for u in new_units:
            produced_ids.add(u.id)
            new_unit_ids.add(u.id)

        embeddings: dict = {}
        if embedder is not None and new_units:
            texts = [u.t1_header for u in new_units]
            vecs = embedder.embed(texts)
            embeddings = {u.id: v for u, v in zip(new_units, vecs)}

        for u in new_units:
            repo.upsert_unit(u, embedding=embeddings.get(u.id))
        for rel in result.relations:
            repo.add_relation(rel)

        stale = existing_ids - produced_ids
        for uid in stale:
            _delete_unit(conn, uid)
        conn.commit()

    return {
        "files_processed": files_processed,
        "units_touched": len(new_unit_ids),
    }


def _delete_unit(conn, uid: str) -> None:
    conn.execute("DELETE FROM relation WHERE src_id = ? OR dst_id = ?", (uid, uid))
    conn.execute("DELETE FROM unit_fts WHERE id = ?", (uid,))
    try:
        conn.execute("DELETE FROM unit_vec WHERE id = ?", (uid,))
    except Exception:
        pass  # vec table may not exist or row absent
    conn.execute("DELETE FROM unit WHERE id = ?", (uid,))

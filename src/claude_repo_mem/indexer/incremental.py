from __future__ import annotations

from contextlib import closing
from pathlib import Path
import re
from typing import Iterable, Optional

import numpy as np

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository
from ..embeddings.base import Embedder
from ..embeddings.validation import validate_embedder
from ..memory.lifecycle import index_memory_unit, restore_supersession
from ..units.model import Unit, Relation
from .orchestrator import _pick_parser, _relativize_scope, _synthesize_graph
from .walker import SUPPORTED_EXTS, walk_repo


GRAPH_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx"}


def incremental_reindex(
    settings: Settings,
    paths: Iterable[Path],
    embedder: Optional[Embedder] = None,
) -> dict:
    """Reparse changed files and atomically refresh their units and code graph.

    Graph synthesis rereads repository sources to reconnect unchanged importers
    and cross-file route declarations, without reparsing unchanged files.
    """
    paths = list(dict.fromkeys(p if p.is_absolute() else settings.repo_root / p for p in paths))
    with closing(connect(settings.db_path)) as conn:
        return _refresh(settings, Repository(conn), paths, embedder)


def _refresh(settings: Settings, repo: Repository, paths: list[Path], embedder: Optional[Embedder]) -> dict:
    if embedder is not None:
        validate_embedder(repo.conn, embedder)
    stored = repo.list_units()
    stored_by_id = {u.id: u for u in stored}
    processed: set[Path] = set()
    parsed: list[Unit] = []
    relations: list[Relation] = []
    sources: dict[Path, str] = {}

    for path in paths:
        if path.suffix.lower() not in SUPPORTED_EXTS:
            continue
        if not path.exists():
            processed.add(path)
            continue
        parser = _pick_parser(path)
        if parser is None:
            continue
        text = _read_source(path)
        result = parser.parse(path, text)
        processed.add(path)
        sources[path] = text
        parsed.extend(_relativize_scope(unit, settings.repo_root) for unit in result.units)
        relations.extend(result.relations)

    changed_ids = {u.id for u in stored if _source_path(u) in processed}
    graph_changed = any(p.suffix.lower() not in {".md", ".markdown"} for p in processed)
    generated: list[Unit] = []
    retained: list[Unit] = []
    route_updates: list[Unit] = []
    if graph_changed:
        retained = [u for u in stored if u.id not in changed_ids and not _is_route(u)]
        for path in walk_repo(settings.repo_root, strict=True):
            if path.suffix.lower() in GRAPH_EXTS and path not in sources:
                sources[path] = _read_source(path)
        generated, graph_relations = _synthesize_graph(retained + parsed, sources, settings.repo_root)
        generated = [_relativize_scope(u, settings.repo_root) for u in generated]
        relations.extend(graph_relations)
        for unit in generated:
            old = stored_by_id.get(unit.id)
            # Keep untouched route summaries, timestamps, and vectors intact.
            if old is None or _route_content(old) != _route_content(unit):
                route_updates.append(unit)

    embeddings: dict[str, np.ndarray] = {}
    if embedder is not None:
        vector_ids = {row[0] for row in repo.conn.execute("SELECT id FROM unit_vec")}
        to_embed = parsed + [u for u in generated if u.id not in vector_ids]
        vectors = embedder.embed([u.t1_header for u in to_embed]) if to_embed else []
        embeddings = {u.id: vector for u, vector in zip(to_embed, vectors)}
        updated_route_ids = {u.id for u in route_updates}
        route_updates.extend(
            stored_by_id[u.id] for u in generated
            if u.id in embeddings and u.id not in updated_route_ids
        )

    written = parsed + route_updates
    written_ids = {u.id for u in written}
    with repo.transaction():
        if graph_changed:
            repo.prune_indexed_units(u.id for u in retained + parsed + generated)
        for unit in written:
            if unit.layer == "memory":
                index_memory_unit(repo, unit, embedding=embeddings.get(unit.id))
            else:
                repo.upsert_unit(unit, embedding=embeddings.get(unit.id))
        restore_supersession(repo, parsed)
        # Code/docs were pruned with the graph; memory-only updates still need
        # to remove old content-addressed handles after restoring supersession.
        stale = changed_ids - written_ids
        if graph_changed:
            stale = {uid for uid in stale if stored_by_id[uid].layer not in {"code", "docs"}}
        repo.delete_units(stale)
        for relation in relations:
            repo.add_relation(relation)

    return {"files_processed": len(paths), "units_touched": len(written_ids)}


def _read_source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        raise ValueError(f"Cannot read {path}; incremental reindex aborted") from exc


def _source_path(unit: Unit) -> Path | None:
    if not unit.source_ref:
        return None
    reference = unit.source_ref
    if unit.layer in {"code", "docs"}:
        reference = re.sub(r":\d+-\d+$", "", reference)
    return Path(reference)


def _is_route(unit: Unit) -> bool:
    return unit.layer == "code" and unit.kind == "route"


def _route_content(unit: Unit) -> tuple:
    return (unit.content_hash, unit.t1_header, unit.source_ref, unit.scope, unit.metadata)

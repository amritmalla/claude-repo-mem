from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from ..config import Settings
from ..db.connection import connect
from ..db.repository import Repository
from ..embeddings.base import Embedder
from ..units.model import Unit, Relation
from .parsers.base import Parser, ParseResult
from .parsers.code_jsts import JsTsParser
from .parsers.code_python import PythonParser
from .parsers.code_java import JavaParser
from .parsers.code_go import GoParser
from .parsers.code_rust import RustParser
from .parsers.markdown import MarkdownParser
from .parsers.memory_md import MemoryMarkdownParser
from .synthesizers.flask_routes import FlaskRoutesSynthesizer
from .synthesizers.django_urls import DjangoUrlsSynthesizer
from .synthesizers.express_routes import ExpressRoutesSynthesizer
from .synthesizers.react_hooks import ReactHooksSynthesizer
from .synthesizers.imports import ImportsSynthesizer
from .walker import walk_repo, hash_file


PARSERS: list[Parser] = [
    MemoryMarkdownParser(),
    PythonParser(), JsTsParser(),
    JavaParser(), GoParser(), RustParser(),
    MarkdownParser(),
]


def full_reindex(settings: Settings, embedder: Optional[Embedder] = None) -> dict:
    repo_root = settings.repo_root
    conn = connect(settings.db_path)
    repository = Repository(conn)

    if embedder is not None:
        row = conn.execute("SELECT name, dim FROM embedder_meta LIMIT 1").fetchone()
        emb_name = getattr(embedder, "name", "unknown")
        if row and (row["name"] != emb_name or row["dim"] != embedder.dim):
            raise ValueError(
                f"embedder mismatch: db has {row['name']}/{row['dim']}, "
                f"got {emb_name}/{embedder.dim}. Run `claude-mem index --reset`."
            )

    all_units: list[Unit] = []
    all_relations: list[Relation] = []
    sources: dict[Path, str] = {}

    for path in walk_repo(repo_root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        parser = _pick_parser(path)
        if not parser:
            continue
        result = parser.parse(path, text)
        all_units.extend(result.units)
        all_relations.extend(result.relations)
        sources[path] = text

    # Synthesizers run on the full snapshot.
    for route_synth in (
        FlaskRoutesSynthesizer(),
        DjangoUrlsSynthesizer(),
        ExpressRoutesSynthesizer(),
    ):
        extra_units, route_rels = route_synth.synthesize_with_units(
            all_units, sources, repo_root
        )
        all_units.extend(extra_units)
        all_relations.extend(route_rels)
    all_relations.extend(ImportsSynthesizer().synthesize(all_units, sources, repo_root))
    all_relations.extend(ReactHooksSynthesizer().synthesize(all_units, sources, repo_root))

    all_units = [_relativize_scope(u, repo_root) for u in all_units]

    # Embeddings (optional — skipped if embedder is None for fast unit tests).
    embeddings: dict[str, np.ndarray] = {}
    if embedder is not None:
        texts = [u.t1_header for u in all_units]
        vecs = embedder.embed(texts)
        embeddings = {u.id: v for u, v in zip(all_units, vecs)}

    for u in all_units:
        repository.upsert_unit(u, embedding=embeddings.get(u.id))
    for r in all_relations:
        repository.add_relation(r)

    if embedder is not None:
        import time
        emb_name = getattr(embedder, "name", "unknown")
        conn.execute(
            "INSERT OR IGNORE INTO embedder_meta(name, dim, created_at) VALUES(?, ?, ?)",
            (emb_name, embedder.dim, int(time.time())),
        )
        conn.commit()

    conn.close()

    return {
        "units_written": len(all_units),
        "relations_written": len(all_relations),
        "files_seen": len(sources),
    }


def _relativize_scope(u: Unit, repo_root: Path) -> Unit:
    """Rewrite absolute path-based scopes to repo-relative form.

    Memory units already use logical scopes (e.g. "backend/auth") — leave them.
    Code/docs units typically have scope = absolute parent dir parts joined; we
    detect that by trying to relativize against repo_root.
    """
    if u.layer == "memory":
        return u
    try:
        rr_parts = repo_root.resolve().parts
        sc_parts = tuple(p for p in u.scope.split("/") if p)
        if len(sc_parts) >= len(rr_parts) and tuple(sc_parts[: len(rr_parts)]) == rr_parts:
            rel = "/".join(sc_parts[len(rr_parts):]) or "root"
            from dataclasses import replace
            return replace(u, scope=rel)
    except (ValueError, OSError):
        pass
    return u


def _pick_parser(path: Path) -> Optional[Parser]:
    for p in PARSERS:
        if p.supports(path):
            return p
    return None

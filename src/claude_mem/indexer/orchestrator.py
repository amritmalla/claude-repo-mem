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
from .parsers.markdown import MarkdownParser
from .synthesizers.flask_routes import FlaskRoutesSynthesizer
from .synthesizers.imports import ImportsSynthesizer
from .walker import walk_repo, hash_file


PARSERS: list[Parser] = [PythonParser(), JsTsParser(), MarkdownParser()]


def full_reindex(settings: Settings, embedder: Optional[Embedder] = None) -> dict:
    repo_root = settings.repo_root
    conn = connect(settings.db_path)
    repository = Repository(conn)

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
    extra_units, route_rels = FlaskRoutesSynthesizer().synthesize_with_units(
        all_units, sources, repo_root
    )
    all_units.extend(extra_units)
    all_relations.extend(route_rels)
    all_relations.extend(ImportsSynthesizer().synthesize(all_units, sources, repo_root))

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

    return {
        "units_written": len(all_units),
        "relations_written": len(all_relations),
        "files_seen": len(sources),
    }


def _pick_parser(path: Path) -> Optional[Parser]:
    for p in PARSERS:
        if p.supports(path):
            return p
    return None

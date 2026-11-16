"""Restore durable memory lifecycle state during indexing."""
from __future__ import annotations

from dataclasses import replace
import json
from typing import Iterable

import numpy as np

from ..db.repository import Repository
from ..units.model import Unit


TOMBSTONE_HANDLE = "tombstone://"


def ensure_tombstone_unit(repo: Repository) -> None:
    """Keep the FK sentinel inactive so it does not appear as a real memory."""
    existing = repo.get_unit(TOMBSTONE_HANDLE)
    if existing is not None:
        if existing.superseded_by != TOMBSTONE_HANDLE:
            repo.upsert_unit(replace(existing, superseded_by=TOMBSTONE_HANDLE))
        return
    repo.upsert_unit(Unit(
        id=TOMBSTONE_HANDLE, layer="memory", kind="fact", scope="_tombstone",
        source_ref=None, content_hash="tombstone", t1_header="[tombstone] forgotten",
        created_at=0, last_seen_at=0, superseded_by=TOMBSTONE_HANDLE,
    ))


def index_memory_unit(repo: Repository, unit: Unit, embedding: np.ndarray | None = None) -> None:
    """Index memory content without reviving an already inactive memory."""
    with repo.transaction():
        if unit.superseded_by == TOMBSTONE_HANDLE:
            ensure_tombstone_unit(repo)
        elif unit.superseded_by is None:
            existing = repo.get_unit(unit.id)
            if existing is not None and existing.superseded_by:
                unit = replace(unit, superseded_by=existing.superseded_by)
        repo.upsert_unit(unit, embedding=embedding)


def restore_supersession(repo: Repository, units: Iterable[Unit]) -> None:
    """Resolve replacement claims after all parsed memories have been stored."""
    with repo.transaction():
        for unit in units:
            if unit.layer != "memory" or not unit.metadata:
                continue
            supersedes = json.loads(unit.metadata).get("supersedes")
            if not supersedes:
                continue
            previous = repo.get_unit(supersedes)
            if previous is not None and previous.superseded_by != TOMBSTONE_HANDLE:
                repo.upsert_unit(replace(previous, superseded_by=unit.id))

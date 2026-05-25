from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

Layer = Literal["memory", "docs", "code", "task"]
_VALID_LAYERS = {"memory", "docs", "code", "task"}


@dataclass(frozen=True)
class Unit:
    id: str
    layer: str
    kind: str
    scope: str
    source_ref: Optional[str]
    content_hash: str
    t1_header: str
    created_at: int
    last_seen_at: int
    t2_summary: Optional[str] = None
    parent_id: Optional[str] = None
    superseded_by: Optional[str] = None
    confidence: Optional[float] = None
    metadata: Optional[str] = None  # JSON string

    def __post_init__(self) -> None:
        if self.layer not in _VALID_LAYERS:
            raise ValueError(f"invalid layer: {self.layer!r}")


@dataclass(frozen=True)
class Relation:
    src_id: str
    dst_id: str
    kind: str

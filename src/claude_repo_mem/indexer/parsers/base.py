from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Protocol

from ...units.model import Unit, Relation


@dataclass(frozen=True)
class ParseResult:
    units: List[Unit] = field(default_factory=list)
    relations: List[Relation] = field(default_factory=list)


class Parser(Protocol):
    """Parses a single file into units (and intra-file relations)."""

    def supports(self, path: Path) -> bool: ...
    def parse(self, path: Path, text: str) -> ParseResult: ...


def now() -> int:
    return int(time.time())

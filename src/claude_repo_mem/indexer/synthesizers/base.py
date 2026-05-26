from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping, Protocol

from ...units.model import Unit, Relation


class Synthesizer(Protocol):
    """Emit cross-unit relations from a parsed repo snapshot."""

    def synthesize(
        self,
        units: Iterable[Unit],
        sources: Mapping[Path, str],
        repo_root: Path,
    ) -> list[Relation]: ...

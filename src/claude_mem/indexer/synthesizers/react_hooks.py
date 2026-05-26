from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Mapping

from ...units.model import Unit, Relation


USE_STATE_RE = re.compile(r"const\s+\[\s*(\w+)\s*,\s*(set\w+)\s*\]\s*=\s*useState\b")
SETTER_USE_RE = re.compile(r"\b(set\w+)\s*\(")
JSX_EXTS = {".jsx", ".tsx"}


class ReactHooksSynthesizer:
    """v1: emit a `mutates_state_of` self-loop on any function whose body both
    declares `[x, setX] = useState(...)` AND calls setX(...).
    """

    def synthesize(
        self,
        units: Iterable[Unit],
        sources: Mapping[Path, str],
        repo_root: Path,
    ) -> List[Relation]:
        by_source: dict[str, list[Unit]] = {}
        for u in units:
            if u.layer == "code" and u.kind in ("function", "method") and u.source_ref:
                file = u.source_ref.rsplit(":", 1)[0]
                by_source.setdefault(file, []).append(u)

        rels: List[Relation] = []
        for path, src in sources.items():
            if path.suffix.lower() not in JSX_EXTS:
                continue
            for u in by_source.get(path.as_posix(), []):
                try:
                    rng = u.source_ref.rsplit(":", 1)[1]
                    start, end = map(int, rng.split("-"))
                except (IndexError, ValueError):
                    continue
                lines = src.splitlines()[start - 1 : end]
                body = "\n".join(lines)
                setters_declared = {m.group(2) for m in USE_STATE_RE.finditer(body)}
                if not setters_declared:
                    continue
                setters_used = {m.group(1) for m in SETTER_USE_RE.finditer(body)}
                if setters_declared & setters_used:
                    rels.append(Relation(u.id, u.id, "mutates_state_of"))
        return rels

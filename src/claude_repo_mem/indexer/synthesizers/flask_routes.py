from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable, List, Mapping, Tuple

from ...units.ids import make_handle
from ...units.model import Unit, Relation
from ..parsers.base import now


ROUTE_RE = re.compile(
    r"@(\w+)\.route\(\s*['\"](?P<path>[^'\"]+)['\"](?:\s*,\s*methods\s*=\s*\[(?P<methods>[^\]]+)\])?\s*\)\s*\n"
    r"def\s+(?P<fn>\w+)\s*\(",
    re.MULTILINE,
)


class FlaskRoutesSynthesizer:
    """Emit a synthetic 'route' unit per @app.route + a route_to edge to its handler."""

    def synthesize_with_units(
        self,
        units: Iterable[Unit],
        sources: Mapping[Path, str],
        repo_root: Path,
    ) -> Tuple[List[Unit], List[Relation]]:
        # Map: (file, function_qualname) -> handler unit.
        # Use rsplit on the LAST colon so Windows drive letters don't truncate.
        handlers: dict[tuple[str, str], Unit] = {}
        for u in units:
            if u.layer == "code" and u.kind in ("function", "method") and u.source_ref:
                file = u.source_ref.rsplit(":", 1)[0]
                # qualname appears in t1_header as `python <name>(...)`
                m = re.match(r"\w+ (\S+?)\(", u.t1_header)
                if m:
                    handlers[(file, m.group(1))] = u

        new_units: List[Unit] = []
        rels: List[Relation] = []
        for path, src in sources.items():
            if path.suffix != ".py":
                continue
            for m in ROUTE_RE.finditer(src):
                route_path = m.group("path")
                methods = m.group("methods") or "GET"
                methods = methods.replace('"', "").replace("'", "").strip()
                fn = m.group("fn")
                handler = handlers.get((path.as_posix(), fn))
                if not handler:
                    continue
                rid_locator = f"{path.as_posix()}::route::{methods}::{route_path}"
                content = f"{methods} {route_path} -> {fn}"
                rid = make_handle("code", "route", rid_locator, content)
                new_units.append(Unit(
                    id=rid,
                    layer="code",
                    kind="route",
                    scope=handler.scope,
                    source_ref=handler.source_ref,
                    content_hash=hashlib.sha256(content.encode()).hexdigest(),
                    t1_header=f"flask route {methods} {route_path} -> {fn}",
                    created_at=now(),
                    last_seen_at=now(),
                    metadata=content,
                ))
                rels.append(Relation(rid, handler.id, "route_to"))
        return new_units, rels

    # Synthesizer protocol — by default no units, just relations.
    def synthesize(self, units, sources, repo_root) -> List[Relation]:
        _, rels = self.synthesize_with_units(units, sources, repo_root)
        return rels

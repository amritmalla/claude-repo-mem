from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable, List, Mapping, Tuple

from ...units.ids import make_handle
from ...units.model import Unit, Relation
from ..parsers.base import now


EXPRESS_RE = re.compile(
    r"""(?P<app>\w+)\.(?P<method>get|post|put|delete|patch|all)\(\s*['"](?P<url>[^'"]+)['"]\s*,\s*(?P<handler>\w+)\s*\)""",
)
JS_EXTS = {".js", ".jsx", ".ts", ".tsx"}


class ExpressRoutesSynthesizer:
    """Emit a synthetic 'route' unit per app.METHOD(url, handler) + route_to edge."""

    def synthesize_with_units(
        self,
        units: Iterable[Unit],
        sources: Mapping[Path, str],
        repo_root: Path,
    ) -> Tuple[List[Unit], List[Relation]]:
        # Same-file handler resolution (named function reference).
        handlers: dict[tuple[str, str], Unit] = {}
        for u in units:
            if u.layer == "code" and u.kind in ("function", "method") and u.source_ref:
                file = u.source_ref.rsplit(":", 1)[0]
                m = re.match(r"\w+ (\S+?)\(", u.t1_header)
                if m:
                    handlers[(file, m.group(1))] = u

        new_units: List[Unit] = []
        rels: List[Relation] = []
        for path, src in sources.items():
            if path.suffix.lower() not in JS_EXTS:
                continue
            for m in EXPRESS_RE.finditer(src):
                method = m.group("method").upper()
                url = m.group("url")
                fn_name = m.group("handler")
                handler = handlers.get((path.as_posix(), fn_name))
                if not handler:
                    continue
                content = f"{method} {url} -> {fn_name}"
                rid_locator = f"{path.as_posix()}::route::{method}::{url}"
                rid = make_handle("code", "route", rid_locator, content)
                new_units.append(Unit(
                    id=rid,
                    layer="code", kind="route", scope=handler.scope,
                    source_ref=handler.source_ref,
                    content_hash=hashlib.sha256(content.encode()).hexdigest(),
                    t1_header=f"express route {method} {url} -> {fn_name}",
                    created_at=now(), last_seen_at=now(),
                    metadata=content,
                ))
                rels.append(Relation(rid, handler.id, "route_to"))
        return new_units, rels

    def synthesize(self, units, sources, repo_root) -> List[Relation]:
        _, rels = self.synthesize_with_units(units, sources, repo_root)
        return rels

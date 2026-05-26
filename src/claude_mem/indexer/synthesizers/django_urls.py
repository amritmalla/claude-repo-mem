from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable, List, Mapping, Tuple

from ...units.ids import make_handle
from ...units.model import Unit, Relation
from ..parsers.base import now


DJANGO_RE = re.compile(
    r"""(?:path|re_path)\(\s*['"](?P<url>[^'"]+)['"]\s*,\s*(?P<handler>[\w.]+)""",
)


class DjangoUrlsSynthesizer:
    """Emit a synthetic 'route' unit per django path()/re_path() + route_to edge."""

    def synthesize_with_units(
        self,
        units: Iterable[Unit],
        sources: Mapping[Path, str],
        repo_root: Path,
    ) -> Tuple[List[Unit], List[Relation]]:
        # Map (parent_dir, fn_name) -> handler unit.
        handlers: dict[tuple[str, str], Unit] = {}
        for u in units:
            if u.layer == "code" and u.kind in ("function", "method") and u.source_ref:
                file = u.source_ref.rsplit(":", 1)[0]
                parent_dir = Path(file).parent.as_posix()
                m = re.match(r"\w+ (\S+?)\(", u.t1_header)
                if m:
                    handlers[(parent_dir, m.group(1))] = u

        new_units: List[Unit] = []
        rels: List[Relation] = []
        for path, src in sources.items():
            if path.name != "urls.py":
                continue
            for m in DJANGO_RE.finditer(src):
                url = m.group("url")
                handler_ref = m.group("handler")
                fn_name = handler_ref.rsplit(".", 1)[-1]
                parent_dir = path.parent.as_posix()
                handler = handlers.get((parent_dir, fn_name))
                if not handler:
                    continue
                content = f"GET {url} -> {fn_name}"
                rid_locator = f"{path.as_posix()}::route::{url}"
                rid = make_handle("code", "route", rid_locator, content)
                new_units.append(Unit(
                    id=rid,
                    layer="code", kind="route", scope=handler.scope,
                    source_ref=handler.source_ref,
                    content_hash=hashlib.sha256(content.encode()).hexdigest(),
                    t1_header=f"django route {url} -> {fn_name}",
                    created_at=now(), last_seen_at=now(),
                    metadata=content,
                ))
                rels.append(Relation(rid, handler.id, "route_to"))
        return new_units, rels

    def synthesize(self, units, sources, repo_root) -> List[Relation]:
        _, rels = self.synthesize_with_units(units, sources, repo_root)
        return rels

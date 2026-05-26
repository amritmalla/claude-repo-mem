from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable, List, Mapping

from ...units.model import Unit, Relation


PY_IMPORT_RE = re.compile(
    r"^(?:from\s+(?P<from>[.\w]+)\s+import\s+\w+|import\s+(?P<mod>[.\w]+))",
    re.MULTILINE,
)
JS_IMPORT_RE = re.compile(
    r"""^\s*(?:import\s+(?:.+?\s+from\s+)?['"](?P<path>[^'"]+)['"]|
            const\s+\S+\s*=\s*require\(['"](?P<rpath>[^'"]+)['"]\))""",
    re.MULTILINE | re.VERBOSE,
)


class ImportsSynthesizer:
    def synthesize(
        self,
        units: Iterable[Unit],
        sources: Mapping[Path, str],
        repo_root: Path,
    ) -> List[Relation]:
        # Build: file_path -> list[unit] for that file
        by_file: dict[Path, list[Unit]] = defaultdict(list)
        for u in units:
            if u.layer != "code" or not u.source_ref:
                continue
            file_part = u.source_ref.rsplit(":", 1)[0]
            by_file[Path(file_part)].append(u)

        # Pick a representative unit per file for the edge target (the parent
        # / file-level unit if any; otherwise the smallest line range).
        def file_target(path: Path) -> Unit | None:
            us = by_file.get(path) or []
            if not us:
                return None
            us = sorted(us, key=lambda u: (u.parent_id is not None, u.source_ref or ""))
            return us[0]

        rels: List[Relation] = []
        for path, src in sources.items():
            if path.suffix == ".py":
                rels.extend(self._py(path, src, repo_root, by_file, file_target))
            elif path.suffix in (".js", ".jsx", ".ts", ".tsx"):
                rels.extend(self._js(path, src, repo_root, by_file, file_target))
        return rels

    def _py(self, path: Path, src: str, root: Path, by_file, file_target) -> List[Relation]:
        rels: List[Relation] = []
        src_unit = file_target(path)
        if not src_unit:
            return rels
        for m in PY_IMPORT_RE.finditer(src):
            ref = m.group("from") or m.group("mod")
            if not ref:
                continue
            target_path = _resolve_py(ref, path, root)
            if target_path is None or target_path not in by_file:
                continue
            tgt = file_target(target_path)
            if tgt and tgt.id != src_unit.id:
                rels.append(Relation(src_unit.id, tgt.id, "imports"))
        return rels

    def _js(self, path: Path, src: str, root: Path, by_file, file_target) -> List[Relation]:
        rels: List[Relation] = []
        src_unit = file_target(path)
        if not src_unit:
            return rels
        for m in JS_IMPORT_RE.finditer(src):
            ref = m.group("path") or m.group("rpath")
            if not ref:
                continue
            target_path = _resolve_js(ref, path)
            if target_path is None or target_path not in by_file:
                continue
            tgt = file_target(target_path)
            if tgt and tgt.id != src_unit.id:
                rels.append(Relation(src_unit.id, tgt.id, "imports"))
        return rels


def _resolve_py(ref: str, importer: Path, root: Path) -> Path | None:
    if ref.startswith("."):
        # relative: count leading dots
        dots = len(ref) - len(ref.lstrip("."))
        parts = ref.lstrip(".").split(".") if ref.lstrip(".") else []
        base = importer.parent
        for _ in range(dots - 1):
            base = base.parent
        candidate = base.joinpath(*parts).with_suffix(".py")
        if candidate.exists():
            return candidate
        pkg = base.joinpath(*parts, "__init__.py")
        if pkg.exists():
            return pkg
        return None
    # absolute: resolve from repo root
    parts = ref.split(".")
    candidate = root.joinpath(*parts).with_suffix(".py")
    if candidate.exists():
        return candidate
    pkg = root.joinpath(*parts, "__init__.py")
    if pkg.exists():
        return pkg
    return None


def _resolve_js(ref: str, importer: Path) -> Path | None:
    if not ref.startswith("."):
        return None  # third-party, skip
    base = importer.parent / ref
    for suffix in (".js", ".jsx", ".ts", ".tsx"):
        candidate = base.with_suffix(suffix)
        if candidate.exists():
            return candidate
    # try as directory with index
    for suffix in (".js", ".jsx", ".ts", ".tsx"):
        candidate = base / f"index{suffix}"
        if candidate.exists():
            return candidate
    return None

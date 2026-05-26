from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from tree_sitter import Language, Parser
import tree_sitter_rust

from ...units.headers import t1_header
from ...units.ids import make_handle
from ...units.model import Unit
from .base import ParseResult, now


@lru_cache(maxsize=1)
def _parser() -> Parser:
    lang = Language(tree_sitter_rust.language())
    try:
        return Parser(lang)
    except TypeError:
        p = Parser()
        try:
            p.language = lang
        except AttributeError:
            p.set_language(lang)
        return p


class RustParser:
    def supports(self, path: Path) -> bool:
        return path.suffix == ".rs"

    def parse(self, path: Path, text: str) -> ParseResult:
        tree = _parser().parse(text.encode("utf-8"))
        scope = _scope_from_path(path)
        units: List[Unit] = []
        _walk(tree.root_node, text, path, scope, units, impl_target=None)
        return ParseResult(units=units)


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _scope_from_path(path: Path) -> str:
    parts = path.parent.parts
    return "/".join(parts) if parts else "root"


def _text_of(node, source: str) -> str:
    return source[node.start_byte : node.end_byte]


def _line_range(node) -> tuple[int, int]:
    return (node.start_point[0] + 1, node.end_point[0] + 1)


def _walk(node, source, path, scope, units, impl_target: Optional[str]):
    for child in node.children:
        t = child.type
        if t == "function_item":
            name_node = child.child_by_field_name("name")
            params_node = child.child_by_field_name("parameters")
            return_node = child.child_by_field_name("return_type")
            name = _text_of(name_node, source) if name_node else "<anon>"
            params = _text_of(params_node, source) if params_node else "()"
            ret = _text_of(return_node, source) if return_node else ""
            sig = f"{params} -> {ret}" if ret else params
            kind = "method" if impl_target else "function"
            qualname = f"impl {impl_target}::{name}" if impl_target else f"fn {name}"
            body_text = _text_of(child, source)
            uid = make_handle("code", kind, f"{path.as_posix()}::{qualname}", body_text)
            header = t1_header(layer="code", kind=kind, lang="rust", name=qualname, signature=sig)
            start, end = _line_range(child)
            units.append(Unit(
                id=uid, layer="code", kind=kind, scope=scope,
                source_ref=f"{path.as_posix()}:{start}-{end}",
                content_hash=_hash(body_text), t1_header=header,
                created_at=now(), last_seen_at=now(), metadata=body_text,
            ))
        elif t in ("struct_item", "trait_item"):
            kind = "struct" if t == "struct_item" else "trait"
            name_node = child.child_by_field_name("name")
            name = _text_of(name_node, source) if name_node else "<anon>"
            body_text = _text_of(child, source)
            uid = make_handle("code", kind, f"{path.as_posix()}::{name}", body_text)
            header = t1_header(layer="code", kind=kind, lang="rust", name=name, signature="")
            start, end = _line_range(child)
            units.append(Unit(
                id=uid, layer="code", kind=kind, scope=scope,
                source_ref=f"{path.as_posix()}:{start}-{end}",
                content_hash=_hash(body_text), t1_header=header,
                created_at=now(), last_seen_at=now(), metadata=body_text,
            ))
            # Walk into trait body for fn signatures (function_signature_item).
            if kind == "trait":
                _walk(child, source, path, scope, units, impl_target=name)
        elif t == "impl_item":
            type_node = child.child_by_field_name("type")
            target = _text_of(type_node, source) if type_node else None
            _walk(child, source, path, scope, units, impl_target=target)
        else:
            _walk(child, source, path, scope, units, impl_target)

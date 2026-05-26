from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from tree_sitter import Language, Parser
import tree_sitter_java

from ...units.headers import t1_header
from ...units.ids import make_handle
from ...units.model import Unit
from .base import ParseResult, now


@lru_cache(maxsize=1)
def _parser() -> Parser:
    lang = Language(tree_sitter_java.language())
    try:
        return Parser(lang)
    except TypeError:
        p = Parser()
        try:
            p.language = lang
        except AttributeError:
            p.set_language(lang)
        return p


class JavaParser:
    def supports(self, path: Path) -> bool:
        return path.suffix == ".java"

    def parse(self, path: Path, text: str) -> ParseResult:
        tree = _parser().parse(text.encode("utf-8"))
        scope = _scope_from_path(path)
        units: List[Unit] = []
        _walk(tree.root_node, text, path, scope, units, parent_id=None, class_name=None)
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


def _method_signature(node, source: str) -> str:
    params_node = node.child_by_field_name("parameters")
    type_node = node.child_by_field_name("type")
    params = _text_of(params_node, source) if params_node else "()"
    ret = _text_of(type_node, source) if type_node else "void"
    return f"{params} -> {ret}"


def _walk(node, source, path, scope, units, parent_id, class_name):
    for child in node.children:
        t = child.type
        if t in ("class_declaration", "interface_declaration"):
            kind = "class" if t == "class_declaration" else "interface"
            name_node = child.child_by_field_name("name")
            name = _text_of(name_node, source) if name_node else "<anon>"
            body_text = _text_of(child, source)
            uid = make_handle("code", kind, f"{path.as_posix()}::{name}", body_text)
            header = t1_header(
                layer="code", kind=kind, lang="java",
                name=name, signature="",
            )
            start, end = _line_range(child)
            units.append(Unit(
                id=uid, layer="code", kind=kind, scope=scope,
                source_ref=f"{path.as_posix()}:{start}-{end}",
                content_hash=_hash(body_text), t1_header=header,
                parent_id=parent_id, created_at=now(), last_seen_at=now(),
                metadata=body_text,
            ))
            body_node = child.child_by_field_name("body")
            if body_node:
                _walk(body_node, source, path, scope, units, parent_id=uid, class_name=name)
        elif t in ("method_declaration", "constructor_declaration"):
            name_node = child.child_by_field_name("name")
            name = _text_of(name_node, source) if name_node else "<anon>"
            sig = _method_signature(child, source)
            body_text = _text_of(child, source)
            qualname = f"{class_name}.{name}" if class_name else name
            uid = make_handle("code", "method", f"{path.as_posix()}::{qualname}", body_text)
            header = t1_header(
                layer="code", kind="method", lang="java",
                name=qualname, signature=sig,
            )
            start, end = _line_range(child)
            units.append(Unit(
                id=uid, layer="code", kind="method", scope=scope,
                source_ref=f"{path.as_posix()}:{start}-{end}",
                content_hash=_hash(body_text), t1_header=header,
                parent_id=parent_id, created_at=now(), last_seen_at=now(),
                metadata=body_text,
            ))
        else:
            _walk(child, source, path, scope, units, parent_id, class_name)

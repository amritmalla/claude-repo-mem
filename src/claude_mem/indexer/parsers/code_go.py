from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import List

from tree_sitter import Language, Parser
import tree_sitter_go

from ...units.headers import t1_header
from ...units.ids import make_handle
from ...units.model import Unit
from .base import ParseResult, now


@lru_cache(maxsize=1)
def _parser() -> Parser:
    lang = Language(tree_sitter_go.language())
    try:
        return Parser(lang)
    except TypeError:
        p = Parser()
        try:
            p.language = lang
        except AttributeError:
            p.set_language(lang)
        return p


class GoParser:
    def supports(self, path: Path) -> bool:
        return path.suffix == ".go"

    def parse(self, path: Path, text: str) -> ParseResult:
        tree = _parser().parse(text.encode("utf-8"))
        scope = _scope_from_path(path)
        units: List[Unit] = []
        _walk(tree.root_node, text, path, scope, units)
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


def _walk(node, source, path, scope, units):
    for child in node.children:
        t = child.type
        if t == "function_declaration":
            name_node = child.child_by_field_name("name")
            params_node = child.child_by_field_name("parameters")
            result_node = child.child_by_field_name("result")
            name = _text_of(name_node, source) if name_node else "<anon>"
            params = _text_of(params_node, source) if params_node else "()"
            ret = _text_of(result_node, source) if result_node else ""
            sig = f"{params} {ret}".strip()
            body_text = _text_of(child, source)
            uid = make_handle("code", "function", f"{path.as_posix()}::{name}", body_text)
            header = t1_header(layer="code", kind="function", lang="go", name=name, signature=sig)
            start, end = _line_range(child)
            units.append(Unit(
                id=uid, layer="code", kind="function", scope=scope,
                source_ref=f"{path.as_posix()}:{start}-{end}",
                content_hash=_hash(body_text), t1_header=header,
                created_at=now(), last_seen_at=now(), metadata=body_text,
            ))
        elif t == "method_declaration":
            name_node = child.child_by_field_name("name")
            receiver_node = child.child_by_field_name("receiver")
            params_node = child.child_by_field_name("parameters")
            result_node = child.child_by_field_name("result")
            name = _text_of(name_node, source) if name_node else "<anon>"
            recv = _text_of(receiver_node, source) if receiver_node else ""
            params = _text_of(params_node, source) if params_node else "()"
            ret = _text_of(result_node, source) if result_node else ""
            qualname = f"{recv} {name}".strip()
            sig = f"{params} {ret}".strip()
            body_text = _text_of(child, source)
            uid = make_handle("code", "method", f"{path.as_posix()}::{qualname}", body_text)
            header = t1_header(layer="code", kind="method", lang="go", name=qualname, signature=sig)
            start, end = _line_range(child)
            units.append(Unit(
                id=uid, layer="code", kind="method", scope=scope,
                source_ref=f"{path.as_posix()}:{start}-{end}",
                content_hash=_hash(body_text), t1_header=header,
                created_at=now(), last_seen_at=now(), metadata=body_text,
            ))
        elif t == "type_declaration":
            # type_spec children carry the actual name + struct/interface body.
            for spec in child.children:
                if spec.type != "type_spec":
                    continue
                name_node = spec.child_by_field_name("name")
                name = _text_of(name_node, source) if name_node else "<anon>"
                body_text = _text_of(spec, source)
                # Determine kind from the type_spec's type child.
                kind = None
                for c in spec.children:
                    if c.type == "struct_type":
                        kind = "struct"
                    elif c.type == "interface_type":
                        kind = "interface"
                if kind is None:
                    continue
                uid = make_handle("code", kind, f"{path.as_posix()}::{name}", body_text)
                header = t1_header(layer="code", kind=kind, lang="go", name=name, signature="")
                start, end = _line_range(spec)
                units.append(Unit(
                    id=uid, layer="code", kind=kind, scope=scope,
                    source_ref=f"{path.as_posix()}:{start}-{end}",
                    content_hash=_hash(body_text), t1_header=header,
                    created_at=now(), last_seen_at=now(), metadata=body_text,
                ))
        else:
            _walk(child, source, path, scope, units)

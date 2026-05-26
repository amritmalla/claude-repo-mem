from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from tree_sitter import Language, Parser
import tree_sitter_javascript
import tree_sitter_typescript

from ...units.headers import t1_header
from ...units.ids import make_handle
from ...units.model import Unit
from .base import ParseResult, now


@lru_cache(maxsize=3)
def _parser_for_suffix(suffix: str) -> Parser:
    if suffix == ".ts":
        lang = Language(tree_sitter_typescript.language_typescript())
    elif suffix == ".tsx":
        lang = Language(tree_sitter_typescript.language_tsx())
    else:  # .js, .jsx
        lang = Language(tree_sitter_javascript.language())
    return Parser(lang)


class JsTsParser:
    def supports(self, path: Path) -> bool:
        return path.suffix in (".js", ".jsx", ".ts", ".tsx")

    def parse(self, path: Path, text: str) -> ParseResult:
        tree = _parser_for_suffix(path.suffix).parse(text.encode("utf-8"))
        scope = _scope_from_path(path)
        units: List[Unit] = []
        _walk(tree.root_node, text, path, scope, units, parent_id=None, class_name=None)
        return ParseResult(units=units)


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _scope_from_path(path: Path) -> str:
    parts = path.parent.parts
    return "/".join(parts) if parts else "root"


def _text(node, source: str) -> str:
    return source[node.start_byte : node.end_byte]


def _lines(node):
    return node.start_point[0] + 1, node.end_point[0] + 1


def _make_fn_unit(name: str, sig: str, body_text: str, path: Path, scope: str,
                   parent_id: Optional[str], class_name: Optional[str],
                   node) -> Unit:
    kind = "method" if class_name else "function"
    qualname = f"{class_name}.{name}" if class_name else name
    uid = make_handle("code", kind, f"{path.as_posix()}::{qualname}", body_text)
    lang = "ts" if path.suffix in (".ts", ".tsx") else "js"
    header = t1_header(
        layer="code", kind=kind, lang=lang,
        name=qualname, signature=sig,
        first_line=body_text.splitlines()[0] if body_text else "",
    )
    s, e = _lines(node)
    return Unit(
        id=uid, layer="code", kind=kind, scope=scope,
        source_ref=f"{path.as_posix()}:{s}-{e}",
        content_hash=_hash(body_text), t1_header=header,
        parent_id=parent_id, created_at=now(), last_seen_at=now(),
        metadata=body_text,
    )


def _walk(node, source: str, path: Path, scope: str,
          units: List[Unit], parent_id: Optional[str], class_name: Optional[str]) -> None:
    for child in node.children:
        t = child.type

        if t == "function_declaration":
            name_node = child.child_by_field_name("name")
            params_node = child.child_by_field_name("parameters")
            name = _text(name_node, source) if name_node else "<anon>"
            sig = _text(params_node, source) if params_node else "()"
            units.append(_make_fn_unit(name, sig, _text(child, source), path, scope,
                                        parent_id, class_name, child))

        elif t == "lexical_declaration":
            # const foo = (args) => body  OR  const foo = function(){...}
            for decl in child.children:
                if decl.type != "variable_declarator":
                    continue
                name_node = decl.child_by_field_name("name")
                value_node = decl.child_by_field_name("value")
                if not name_node or not value_node:
                    continue
                if value_node.type in ("arrow_function", "function_expression"):
                    name = _text(name_node, source)
                    params_node = value_node.child_by_field_name("parameters")
                    sig = _text(params_node, source) if params_node else "()"
                    units.append(_make_fn_unit(name, sig, _text(decl, source), path, scope,
                                                parent_id, class_name, decl))

        elif t == "class_declaration":
            name_node = child.child_by_field_name("name")
            name = _text(name_node, source) if name_node else "<anon>"
            body_text = _text(child, source)
            uid = make_handle("code", "class", f"{path.as_posix()}::{name}", body_text)
            lang = "ts" if path.suffix in (".ts", ".tsx") else "js"
            header = t1_header(
                layer="code", kind="class", lang=lang,
                name=name, signature="",
                first_line=body_text.splitlines()[0] if body_text else "",
            )
            s, e = _lines(child)
            units.append(Unit(
                id=uid, layer="code", kind="class", scope=scope,
                source_ref=f"{path.as_posix()}:{s}-{e}",
                content_hash=_hash(body_text), t1_header=header,
                parent_id=parent_id, created_at=now(), last_seen_at=now(),
                metadata=body_text,
            ))
            body_node = child.child_by_field_name("body")
            if body_node:
                _walk(body_node, source, path, scope, units, parent_id=uid, class_name=name)

        elif t == "method_definition":
            name_node = child.child_by_field_name("name")
            params_node = child.child_by_field_name("parameters")
            name = _text(name_node, source) if name_node else "<anon>"
            sig = _text(params_node, source) if params_node else "()"
            units.append(_make_fn_unit(name, sig, _text(child, source), path, scope,
                                        parent_id, class_name, child))

        else:
            _walk(child, source, path, scope, units, parent_id, class_name)

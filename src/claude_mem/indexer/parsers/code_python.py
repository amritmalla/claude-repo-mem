from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from tree_sitter import Language, Parser
import tree_sitter_python

from ...units.headers import t1_header
from ...units.ids import make_handle
from ...units.model import Unit
from .base import ParseResult, now


@lru_cache(maxsize=1)
def _parser() -> Parser:
    # tree-sitter >= 0.22: Language wraps the capsule returned by tree_sitter_python.language().
    # Try Parser(lang) first; fall back to property or set_language for older builds.
    lang = Language(tree_sitter_python.language())
    try:
        return Parser(lang)
    except TypeError:
        p = Parser()
        try:
            p.language = lang
        except AttributeError:
            p.set_language(lang)
        return p


class PythonParser:
    def supports(self, path: Path) -> bool:
        return path.suffix == ".py"

    def parse(self, path: Path, text: str) -> ParseResult:
        tree = _parser().parse(text.encode("utf-8"))
        scope = _scope_from_path(path)
        units: List[Unit] = []
        _walk(tree.root_node, text, path, scope, units, parent_id=None, class_name=None)
        return ParseResult(units=units)


# -- helpers ---------------------------------------------------------------

def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _scope_from_path(path: Path) -> str:
    parts = path.parent.parts
    return "/".join(parts) if parts else "root"


def _text_of(node, source: str) -> str:
    return source[node.start_byte : node.end_byte]


def _line_range(node) -> tuple[int, int]:
    return (node.start_point[0] + 1, node.end_point[0] + 1)


def _signature(node, source: str) -> str:
    """Extract `(params) -> return` from a function_definition node."""
    params_node = node.child_by_field_name("parameters")
    return_node = node.child_by_field_name("return_type")
    params = _text_of(params_node, source) if params_node else "()"
    if return_node:
        return f"{params} -> {_text_of(return_node, source)}"
    return params


def _docstring_first_line(node, source: str) -> Optional[str]:
    body = node.child_by_field_name("body")
    if not body or body.child_count == 0:
        return None
    first = body.children[0]
    if first.type == "expression_statement" and first.child_count == 1:
        s = first.children[0]
        if s.type == "string":
            text = _text_of(s, source).strip()
            # strip quotes
            for q in ('"""', "'''", '"', "'"):
                if text.startswith(q):
                    text = text[len(q):]
                    if text.endswith(q):
                        text = text[: -len(q)]
                    break
            return text.split("\n", 1)[0].strip() or None
    return None


def _walk(node, source: str, path: Path, scope: str,
          units: List[Unit], parent_id: Optional[str], class_name: Optional[str]) -> None:
    for child in node.children:
        if child.type == "function_definition":
            name_node = child.child_by_field_name("name")
            name = _text_of(name_node, source) if name_node else "<anon>"
            sig = _signature(child, source)
            body_text = _text_of(child, source)
            kind = "method" if class_name else "function"
            qualname = f"{class_name}.{name}" if class_name else name
            uid = make_handle("code", kind, f"{path.as_posix()}::{qualname}", body_text)
            header = t1_header(
                layer="code", kind=kind, lang="python",
                name=qualname, signature=sig,
                first_line=body_text.splitlines()[0] if body_text else "",
            )
            start, end = _line_range(child)
            units.append(
                Unit(
                    id=uid,
                    layer="code",
                    kind=kind,
                    scope=scope,
                    source_ref=f"{path.as_posix()}:{start}-{end}",
                    content_hash=_hash(body_text),
                    t1_header=header,
                    parent_id=parent_id,
                    created_at=now(),
                    last_seen_at=now(),
                    metadata=body_text,
                )
            )
        elif child.type == "class_definition":
            name_node = child.child_by_field_name("name")
            name = _text_of(name_node, source) if name_node else "<anon>"
            superclasses_node = child.child_by_field_name("superclasses")
            superclasses = _text_of(superclasses_node, source) if superclasses_node else ""
            body_text = _text_of(child, source)
            doc = _docstring_first_line(child, source)
            uid = make_handle("code", "class", f"{path.as_posix()}::{name}", body_text)
            header = t1_header(
                layer="code", kind="class", lang="python",
                name=name, signature=superclasses,
                first_line=body_text.splitlines()[0] if body_text else "",
                docstring_first_line=doc,
            )
            start, end = _line_range(child)
            units.append(
                Unit(
                    id=uid,
                    layer="code",
                    kind="class",
                    scope=scope,
                    source_ref=f"{path.as_posix()}:{start}-{end}",
                    content_hash=_hash(body_text),
                    t1_header=header,
                    parent_id=parent_id,
                    created_at=now(),
                    last_seen_at=now(),
                    metadata=body_text,
                )
            )
            body_node = child.child_by_field_name("body")
            if body_node:
                _walk(body_node, source, path, scope, units, parent_id=uid, class_name=name)
        else:
            # Recurse into module-level blocks (e.g. `if __name__` guards).
            _walk(child, source, path, scope, units, parent_id, class_name)

from __future__ import annotations

from typing import Optional, Sequence

MEMORY_BODY_CHARS = 80


def t1_header(
    *,
    layer: str,
    kind: str,
    # Code:
    lang: Optional[str] = None,
    name: Optional[str] = None,
    signature: Optional[str] = None,
    first_line: Optional[str] = None,
    docstring_first_line: Optional[str] = None,
    # Docs:
    heading_path: Optional[Sequence[str]] = None,
    # Memory:
    text: Optional[str] = None,
) -> str:
    """Compute T1 header per spec §9.3."""
    if layer == "code":
        if name is None:
            raise ValueError("code header needs name")
        sig = signature or ""
        base = f"{lang or 'code'} {name}{sig}".strip()
        if kind in ("class", "interface"):
            base = f"{lang or 'code'} {kind} {name}{sig}"
            if docstring_first_line:
                base = f"{base}: {docstring_first_line}"
        return base

    if layer == "docs":
        if not heading_path:
            raise ValueError("docs header needs heading_path")
        return "# " + " > ".join(heading_path)

    if layer in ("memory", "task"):
        if text is None:
            raise ValueError("memory/task header needs text")
        body = text.strip().replace("\n", " ")[:MEMORY_BODY_CHARS]
        return f"[{kind}] {body}"

    raise ValueError(f"unknown layer for header: {layer!r}")

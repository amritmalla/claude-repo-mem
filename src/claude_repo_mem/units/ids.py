from __future__ import annotations

import hashlib
from dataclasses import dataclass

VALID_LAYERS = {"memory", "docs", "code", "task"}


@dataclass(frozen=True)
class HandleParts:
    layer: str
    kind: str
    short_hash: str


def make_handle(layer: str, kind: str, locator: str, content: str) -> str:
    """Deterministic, content-addressed handle.

    `locator` is a stable name (e.g. `module.function`, `path#heading`). It plus
    content seed the hash so that renames produce new handles but identical
    content at the same locator collides (good — it's the same unit).
    """
    if layer not in VALID_LAYERS:
        raise ValueError(f"invalid layer: {layer!r}")
    digest = hashlib.sha256(f"{locator}\0{content}".encode("utf-8")).hexdigest()
    return f"{layer}://{kind}/{digest[:12]}"


def parse_handle(handle: str) -> HandleParts:
    if "://" not in handle:
        raise ValueError(f"not a claude-repo-mem handle: {handle!r}")
    layer, rest = handle.split("://", 1)
    if layer not in VALID_LAYERS:
        raise ValueError(f"invalid handle layer: {layer!r}")
    if "/" not in rest:
        raise ValueError(f"malformed handle: {handle!r}")
    kind, short = rest.split("/", 1)
    return HandleParts(layer=layer, kind=kind, short_hash=short)

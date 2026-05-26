from __future__ import annotations

import os
from typing import Optional

from .base import Embedder


def make_embedder(name: Optional[str] = None) -> Embedder:
    choice = (name or os.environ.get("CLAUDE_REPO_MEM_EMBEDDER", "bge-small")).lower()
    if choice == "bge-small":
        from .bge_small import BgeSmallEmbedder
        return BgeSmallEmbedder()
    if choice == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY not set for openai embedder")
        from .openai_emb import OpenAiEmbedder
        return OpenAiEmbedder()
    if choice == "voyage":
        if not os.environ.get("VOYAGE_API_KEY"):
            raise ValueError("VOYAGE_API_KEY not set for voyage embedder")
        from .voyage_emb import VoyageEmbedder
        return VoyageEmbedder()
    raise ValueError(f"unknown embedder: {choice!r}")

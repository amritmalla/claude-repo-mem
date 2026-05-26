from __future__ import annotations

import os
from typing import Sequence

import numpy as np

try:
    import voyageai  # type: ignore
except ImportError:  # pragma: no cover
    voyageai = None  # type: ignore


class VoyageEmbedder:
    name = "voyage"
    dim = 512  # voyage-3-lite default

    def __init__(self, model: str = "voyage-3-lite") -> None:
        if voyageai is None:
            raise ImportError("voyageai package not installed; pip install voyageai")
        key = os.environ.get("VOYAGE_API_KEY")
        if not key:
            raise ValueError("VOYAGE_API_KEY not set")
        self.client = voyageai.Client(api_key=key)
        self.model = model

    def embed(self, texts: Sequence[str]) -> list[np.ndarray]:
        if not texts:
            return []
        result = self.client.embed(list(texts), model=self.model)
        return [np.asarray(v, dtype=np.float32) for v in result.embeddings]

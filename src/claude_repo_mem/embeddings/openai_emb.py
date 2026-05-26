from __future__ import annotations

import os
from typing import Sequence

import numpy as np

try:
    from openai import OpenAI  # type: ignore
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore


class OpenAiEmbedder:
    name = "openai"
    dim = 1536  # text-embedding-3-small default

    def __init__(self, model: str = "text-embedding-3-small") -> None:
        if OpenAI is None:
            raise ImportError("openai package not installed; pip install openai")
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("OPENAI_API_KEY not set")
        self.client = OpenAI(api_key=key)
        self.model = model

    def embed(self, texts: Sequence[str]) -> list[np.ndarray]:
        if not texts:
            return []
        resp = self.client.embeddings.create(model=self.model, input=list(texts))
        return [np.asarray(d.embedding, dtype=np.float32) for d in resp.data]

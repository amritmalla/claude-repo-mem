from __future__ import annotations

from functools import cached_property
from typing import Sequence

import numpy as np


class BgeSmallEmbedder:
    """sentence-transformers/BAAI/bge-small-en-v1.5, 384-dim, CPU."""

    name = "bge-small"
    dim = 384
    model_id = "BAAI/bge-small-en-v1.5"

    @cached_property
    def _model(self):
        # Imported lazily so unit tests that mock the embedder don't pay the import.
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(self.model_id, device="cpu")

    def embed(self, texts: Sequence[str]) -> list[np.ndarray]:
        if not texts:
            return []
        arr = self._model.encode(
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        ).astype("float32")
        return [row for row in arr]

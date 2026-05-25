from __future__ import annotations

from typing import Protocol, Sequence

import numpy as np


class Embedder(Protocol):
    dim: int = ...  # type: ignore[assignment]

    def embed(self, texts: Sequence[str]) -> list[np.ndarray]: ...

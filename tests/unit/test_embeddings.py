import numpy as np
import pytest

from claude_repo_mem.embeddings.base import Embedder
from claude_repo_mem.embeddings.bge_small import BgeSmallEmbedder


def test_embedder_protocol_attrs():
    assert hasattr(Embedder, "embed")
    assert hasattr(Embedder, "dim")


@pytest.mark.slow
def test_bge_small_embeds_single():
    e = BgeSmallEmbedder()
    [v] = e.embed(["hello world"])
    assert v.shape == (384,)
    assert v.dtype == np.float32


@pytest.mark.slow
def test_bge_small_batch():
    e = BgeSmallEmbedder()
    vs = e.embed(["alpha", "beta", "gamma"])
    assert len(vs) == 3
    assert all(v.shape == (384,) for v in vs)


@pytest.mark.slow
def test_bge_small_similar_texts_closer():
    e = BgeSmallEmbedder()
    a, b, c = e.embed(["user authentication", "user login", "database migration"])
    sim_ab = float(np.dot(a, b))
    sim_ac = float(np.dot(a, c))
    assert sim_ab > sim_ac

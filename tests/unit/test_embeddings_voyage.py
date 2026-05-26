import pytest
from unittest.mock import patch, MagicMock
import numpy as np


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("VOYAGE_API_KEY", "vy-fake")


def test_name_and_dim(env):
    with patch("claude_mem.embeddings.voyage_emb.voyageai"):
        from claude_mem.embeddings.voyage_emb import VoyageEmbedder
        e = VoyageEmbedder()
    assert e.name == "voyage"
    assert e.dim == 512


def test_embed_returns_float_vectors(env):
    with patch("claude_mem.embeddings.voyage_emb.voyageai") as vy:
        vy.Client.return_value.embed.return_value = MagicMock(
            embeddings=[[0.1] * 512, [0.2] * 512]
        )
        from claude_mem.embeddings.voyage_emb import VoyageEmbedder
        out = VoyageEmbedder().embed(["a", "b"])
    assert len(out) == 2
    assert out[0].shape == (512,)
    assert out[0].dtype == np.float32


def test_embed_empty_returns_empty(env):
    with patch("claude_mem.embeddings.voyage_emb.voyageai"):
        from claude_mem.embeddings.voyage_emb import VoyageEmbedder
        assert VoyageEmbedder().embed([]) == []


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    with patch("claude_mem.embeddings.voyage_emb.voyageai"):
        from claude_mem.embeddings.voyage_emb import VoyageEmbedder
        with pytest.raises(ValueError):
            VoyageEmbedder()

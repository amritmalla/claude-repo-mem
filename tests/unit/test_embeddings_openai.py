import pytest
from unittest.mock import patch, MagicMock
import numpy as np


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")


def test_name_and_dim(env):
    with patch("claude_mem.embeddings.openai_emb.OpenAI"):
        from claude_mem.embeddings.openai_emb import OpenAiEmbedder
        e = OpenAiEmbedder()
    assert e.name == "openai"
    assert e.dim == 1536


def test_embed_returns_float_vectors(env):
    with patch("claude_mem.embeddings.openai_emb.OpenAI") as Client:
        Client.return_value.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=[0.1] * 1536), MagicMock(embedding=[0.2] * 1536)]
        )
        from claude_mem.embeddings.openai_emb import OpenAiEmbedder
        e = OpenAiEmbedder()
        out = e.embed(["a", "b"])
    assert len(out) == 2
    assert out[0].shape == (1536,)
    assert out[0].dtype == np.float32


def test_embed_empty_returns_empty(env):
    with patch("claude_mem.embeddings.openai_emb.OpenAI"):
        from claude_mem.embeddings.openai_emb import OpenAiEmbedder
        assert OpenAiEmbedder().embed([]) == []


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with patch("claude_mem.embeddings.openai_emb.OpenAI"):
        from claude_mem.embeddings.openai_emb import OpenAiEmbedder
        with pytest.raises(ValueError):
            OpenAiEmbedder()

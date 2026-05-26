import pytest
from claude_mem.embeddings.factory import make_embedder


def test_default_is_bge_small(monkeypatch):
    monkeypatch.delenv("CLAUDE_MEM_EMBEDDER", raising=False)
    e = make_embedder()
    assert e.name == "bge-small"
    assert e.dim == 384


def test_explicit_bge_small(monkeypatch):
    monkeypatch.setenv("CLAUDE_MEM_EMBEDDER", "bge-small")
    assert make_embedder().name == "bge-small"


def test_unknown_value_raises(monkeypatch):
    monkeypatch.setenv("CLAUDE_MEM_EMBEDDER", "bogus")
    with pytest.raises(ValueError):
        make_embedder()


def test_openai_missing_key_raises(monkeypatch):
    monkeypatch.setenv("CLAUDE_MEM_EMBEDDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError):
        make_embedder()


def test_voyage_missing_key_raises(monkeypatch):
    monkeypatch.setenv("CLAUDE_MEM_EMBEDDER", "voyage")
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    with pytest.raises(ValueError):
        make_embedder()

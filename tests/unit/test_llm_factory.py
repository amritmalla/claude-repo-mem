import pytest
from unittest.mock import MagicMock

from claude_repo_mem.llm.factory import make_llm_client
from claude_repo_mem.llm.mcp_sampling import McpSamplingClient
from claude_repo_mem.llm.base import LLMError


def test_default_is_mcp(monkeypatch):
    monkeypatch.delenv("CLAUDE_REPO_MEM_LLM", raising=False)
    ctx = MagicMock()
    c = make_llm_client(ctx=ctx)
    assert isinstance(c, McpSamplingClient)


def test_explicit_mcp(monkeypatch):
    monkeypatch.setenv("CLAUDE_REPO_MEM_LLM", "mcp")
    c = make_llm_client(ctx=MagicMock())
    assert isinstance(c, McpSamplingClient)


def test_mcp_without_ctx_raises(monkeypatch):
    monkeypatch.setenv("CLAUDE_REPO_MEM_LLM", "mcp")
    with pytest.raises(LLMError):
        make_llm_client(ctx=None)


def test_unknown_value_raises(monkeypatch):
    monkeypatch.setenv("CLAUDE_REPO_MEM_LLM", "bogus")
    with pytest.raises(LLMError):
        make_llm_client(ctx=MagicMock())

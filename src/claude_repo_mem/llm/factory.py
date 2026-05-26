from __future__ import annotations

import os
from typing import Any

from .base import LLMClient, LLMError
from .mcp_sampling import McpSamplingClient


def make_llm_client(*, ctx: Any | None = None) -> LLMClient:
    choice = os.environ.get("CLAUDE_REPO_MEM_LLM", "mcp").lower()
    if choice == "mcp":
        if ctx is None:
            raise LLMError(
                "MCP sampling client requires an MCP Context; "
                "ensure the tool handler is wired to receive one."
            )
        return McpSamplingClient(ctx)
    if choice == "anthropic":
        try:
            from .anthropic_api import AnthropicApiClient  # type: ignore
        except ImportError as e:
            raise LLMError(
                "anthropic LLM client not yet available; "
                "see Task 16 in the Phase 2 plan."
            ) from e
        return AnthropicApiClient()
    raise LLMError(f"unknown CLAUDE_REPO_MEM_LLM value: {choice!r}")

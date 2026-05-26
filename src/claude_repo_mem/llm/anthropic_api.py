from __future__ import annotations

import os
from .base import LLMError


class AnthropicApiClient:
    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("ANTHROPIC_API_KEY not set")
        try:
            from anthropic import AsyncAnthropic  # type: ignore
        except ImportError as e:
            raise LLMError("anthropic package not installed") from e
        self.client = AsyncAnthropic(api_key=key)
        self.model = model

    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        try:
            resp = await self.client.messages.create(
                model=self.model,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            raise LLMError(f"Anthropic API call failed: {e}") from e
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                return getattr(block, "text", "")
        return ""

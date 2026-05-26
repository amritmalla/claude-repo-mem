from __future__ import annotations

from typing import Any

from .base import LLMClient, LLMError


class McpSamplingClient:
    """LLMClient that asks the MCP host for sampling via `ctx.session.create_message`."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        try:
            result = await self.ctx.session.create_message(
                messages=[{"role": "user", "content": user}],
                system_prompt=system,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except TypeError:
            try:
                result = await self.ctx.session.create_message(
                    messages=[{"role": "user", "content": user}],
                    system=system,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            except Exception as e:
                raise LLMError(f"MCP sampling failed: {e}") from e
        except Exception as e:
            raise LLMError(f"MCP sampling failed: {e}") from e

        content = getattr(result, "content", None) or []
        for item in content:
            if getattr(item, "type", None) == "text":
                return getattr(item, "text", "") or ""
        return ""

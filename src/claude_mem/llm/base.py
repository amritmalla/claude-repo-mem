from __future__ import annotations

from typing import Protocol


class LLMError(Exception):
    """Raised by LLMClient implementations on any failure."""


class LLMClient(Protocol):
    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str: ...

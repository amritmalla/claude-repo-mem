import pytest
from unittest.mock import AsyncMock, MagicMock

from claude_mem.llm.mcp_sampling import McpSamplingClient
from claude_mem.llm.base import LLMError


@pytest.mark.asyncio
async def test_complete_calls_create_message():
    ctx = MagicMock()
    ctx.session.create_message = AsyncMock(return_value=MagicMock(
        content=[MagicMock(type="text", text="hello back")]
    ))
    client = McpSamplingClient(ctx)
    out = await client.complete("sys", "usr", max_tokens=100)
    assert out == "hello back"
    ctx.session.create_message.assert_called_once()


@pytest.mark.asyncio
async def test_complete_passes_system_and_user():
    ctx = MagicMock()
    ctx.session.create_message = AsyncMock(return_value=MagicMock(
        content=[MagicMock(type="text", text="x")]
    ))
    await McpSamplingClient(ctx).complete("system text", "user text")
    kwargs = ctx.session.create_message.call_args.kwargs
    serialized = repr(kwargs)
    assert "system text" in serialized
    assert "user text" in serialized


@pytest.mark.asyncio
async def test_complete_raises_llmerror_on_underlying_failure():
    ctx = MagicMock()
    ctx.session.create_message = AsyncMock(side_effect=RuntimeError("boom"))
    with pytest.raises(LLMError):
        await McpSamplingClient(ctx).complete("s", "u")


@pytest.mark.asyncio
async def test_complete_handles_no_text_content():
    ctx = MagicMock()
    ctx.session.create_message = AsyncMock(return_value=MagicMock(content=[]))
    out = await McpSamplingClient(ctx).complete("s", "u")
    assert out == ""

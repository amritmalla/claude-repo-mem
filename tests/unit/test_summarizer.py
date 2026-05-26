import pytest
from unittest.mock import AsyncMock
from claude_mem.summarizer.summarize import summarize_unit
from claude_mem.units.model import Unit


def _u(layer, kind, body):
    return Unit(
        id=f"{layer}://{kind}/a", layer=layer, kind=kind, scope="x",
        source_ref=None, content_hash="h", t1_header="t",
        created_at=0, last_seen_at=0,
        metadata=body,
    )


@pytest.mark.asyncio
async def test_summarize_function_unit():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="Calls verify_user, returns token.")
    u = _u("code", "function", "def login(user, pw):\n    if verify_user(user, pw):\n        return issue_token(user)\n    raise Unauthorized")
    summary = await summarize_unit(u, llm)
    assert "verify_user" in summary
    llm.complete.assert_called_once()


@pytest.mark.asyncio
async def test_summarize_section_unit_uses_doc_prompt():
    llm = AsyncMock(); llm.complete = AsyncMock(return_value="X is described.")
    u = _u("docs", "section", "# Authentication\n\nWe use POST /login to issue tokens. " * 5)
    await summarize_unit(u, llm)
    kwargs = llm.complete.call_args.kwargs
    assert "doc" in kwargs["system"].lower()


@pytest.mark.asyncio
async def test_summarize_memory_unit_returns_none():
    llm = AsyncMock()
    u = _u("memory", "decision", "We use JWT.")
    summary = await summarize_unit(u, llm)
    assert summary is None
    llm.complete.assert_not_called()


@pytest.mark.asyncio
async def test_summarize_handles_llm_error():
    from claude_mem.llm.base import LLMError
    llm = AsyncMock(); llm.complete = AsyncMock(side_effect=LLMError("nope"))
    u = _u("code", "function", "def x(): pass" + "\n# big body here " * 20)
    summary = await summarize_unit(u, llm)
    assert summary is None

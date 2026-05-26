import json
import pytest
from unittest.mock import AsyncMock
from claude_repo_mem.distill.extract import extract_memories
from claude_repo_mem.distill.transcript import ChatTurn


@pytest.mark.asyncio
async def test_extract_parses_proposals():
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=json.dumps({
        "proposals": [
            {"kind": "decision", "scope": "backend/auth", "confidence": 0.9, "fact": "Use JWT"},
            {"kind": "convention", "scope": "tooling", "confidence": 0.7, "fact": "Always run pytest -q"},
        ]
    }))
    turns = [ChatTurn(role="user", content="we use JWT"), ChatTurn(role="assistant", content="ok")]
    proposals = await extract_memories(turns, llm)
    assert len(proposals) == 2
    assert proposals[0].fact == "Use JWT"
    assert proposals[0].confidence == 0.9


@pytest.mark.asyncio
async def test_extract_empty_on_malformed():
    llm = AsyncMock(); llm.complete = AsyncMock(return_value="not json")
    turns = [ChatTurn(role="user", content="x")]
    assert await extract_memories(turns, llm) == []


@pytest.mark.asyncio
async def test_extract_no_turns_no_call():
    llm = AsyncMock()
    assert await extract_memories([], llm) == []
    llm.complete.assert_not_called()


@pytest.mark.asyncio
async def test_extract_filters_invalid_kind():
    llm = AsyncMock(); llm.complete = AsyncMock(return_value=json.dumps({
        "proposals": [{"kind": "bogus", "scope": "x", "fact": "thing", "confidence": 0.5}]
    }))
    proposals = await extract_memories([ChatTurn(role="user", content="x")], llm)
    assert proposals[0].kind == "fact"  # fell back

import pytest

from claude_mem.server import build_server, SERVER_INSTRUCTIONS


def test_server_builds():
    server = build_server()
    assert server is not None


def test_instructions_mention_recall_and_trace():
    assert "recall" in SERVER_INSTRUCTIONS.lower()
    assert "trace" in SERVER_INSTRUCTIONS.lower()
    assert "before reading files" in SERVER_INSTRUCTIONS.lower() or "before native" in SERVER_INSTRUCTIONS.lower()


@pytest.mark.asyncio
async def test_list_tools():
    server = build_server()
    tools = await _list_tools(server)
    names = [t.name for t in tools]
    assert "recall" in names
    assert "trace" in names
    assert "expand" in names


async def _list_tools(server):
    """Adapter to extract tool list across MCP SDK versions.

    Installed SDK variant: Server(name=, instructions=) accepted directly.
    list_tools() decorator registers handler in server.request_handlers keyed
    by ListToolsRequest. We use the request_handlers path since list_tools()
    returns a decorator, not a coroutine.
    """
    # Try the request_handlers mapping (low-level)
    handlers = getattr(server, "request_handlers", None)
    if handlers:
        from mcp.types import ListToolsRequest
        handler = handlers.get(ListToolsRequest)
        if handler:
            req = ListToolsRequest(method="tools/list", params=None)
            res = await handler(req)
            return list(res.root.tools)
    raise RuntimeError("Could not extract tool list from MCP server")

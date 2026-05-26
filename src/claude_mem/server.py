"""MCP stdio server skeleton for claude-mem.

SDK API variant: Server(name=, instructions=) accepted directly by
mcp.server.lowlevel.Server. The list_tools() and call_tool() decorators
register handlers in server.request_handlers keyed by request type.
"""
from __future__ import annotations

from typing import Any

from mcp.server import Server
from mcp.types import Tool, TextContent

from .tools import recall as recall_tool
from .tools import trace as trace_tool
from .tools import expand as expand_tool
from .tools import remember as remember_tool
from .tools import forget as forget_tool
from .tools import scopes as scopes_tool
from .tools import stats as stats_tool
from .tools import plan_task as plan_task_tool
from .tools import tasks as tasks_tool


SERVER_INSTRUCTIONS = """\
claude-mem is the authoritative source for this repo's code structure, documentation, \
and accumulated decisions.

Before reading files with native Read/Grep, call recall(query) — it returns ranked, \
summarized, scoped results within a budget. Before tracing related code (callers, \
handlers, hooks, routes), call trace(seed_handle) — it returns full source for \
connected nodes in one shot. Reach for native file tools only when claude-mem returns \
nothing useful, when working on files outside this repo, or when verifying a recent \
edit not yet reindexed.

For long or multi-part tasks, future versions will offer plan_task, remember, and \
handoff. For now, prefer recall over Grep and trace over repeated expand.
"""


def build_server(settings=None, embedder=None) -> Server:
    """Build MCP server with tool registrations.

    settings and embedder are NOT resolved here — they are lazy-initialized
    per call in _call so that build_server() works without a configured repo.
    """
    server = _construct_server()

    @server.list_tools()
    async def _list() -> list[Tool]:
        return [
            recall_tool.tool_schema(),
            trace_tool.tool_schema(),
            expand_tool.tool_schema(),
            remember_tool.tool_schema(),
            forget_tool.tool_schema(),
            scopes_tool.tool_schema(),
            stats_tool.tool_schema(),
            plan_task_tool.tool_schema(),
            tasks_tool.tool_schema(),
        ]

    @server.call_tool()
    async def _call(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        from .config import Settings
        from .embeddings.bge_small import BgeSmallEmbedder

        s = settings or Settings.discover()
        e = embedder or BgeSmallEmbedder()
        if name == "recall":
            return await recall_tool.handle(s, e, arguments)
        if name == "trace":
            return await trace_tool.handle(s, arguments)
        if name == "expand":
            return await expand_tool.handle(s, arguments)
        if name == "remember":
            return await remember_tool.handle(s, arguments)
        if name == "forget":
            return await forget_tool.handle(s, arguments)
        if name == "scopes":
            return await scopes_tool.handle(s, arguments)
        if name == "stats":
            return await stats_tool.handle(s, arguments)
        if name == "plan_task":
            from .llm.factory import make_llm_client
            llm = make_llm_client(ctx=None)  # falls back appropriately; sampling Context wiring is a later refinement
            return await plan_task_tool.handle(s, llm, arguments)
        if name == "tasks":
            return await tasks_tool.handle(s, arguments)
        return [TextContent(type="text", text=f"unknown tool: {name}")]

    return server


def _construct_server() -> Server:
    """Construct Server across SDK API variants.

    Installed SDK (mcp lowlevel) accepts Server(name=, instructions=) directly.
    Falls back to post-construction attribute assignment if TypeError is raised.
    """
    try:
        return Server(name="claude-mem", instructions=SERVER_INSTRUCTIONS)
    except TypeError:
        s = Server(name="claude-mem")
        try:
            s.instructions = SERVER_INSTRUCTIONS
        except AttributeError:
            pass
        return s


async def serve_stdio() -> None:
    from mcp.server.stdio import stdio_server

    server = build_server()
    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())

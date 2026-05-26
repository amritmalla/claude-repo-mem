from mcp.types import Tool, TextContent


async def handle(settings, embedder, args):
    return [TextContent(type="text", text="stub")]


def tool_schema() -> Tool:
    return Tool(name="recall", description="stub", inputSchema={"type": "object"})

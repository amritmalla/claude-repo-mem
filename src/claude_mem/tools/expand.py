from mcp.types import Tool, TextContent


async def handle(settings, args):
    return [TextContent(type="text", text="stub")]


def tool_schema() -> Tool:
    return Tool(name="expand", description="stub", inputSchema={"type": "object"})

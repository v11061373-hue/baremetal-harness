import re

from baremetal_harness.mcp.client import StdioMcpClient
from baremetal_harness.mcp.types import McpError, McpTool
from baremetal_harness.tools.types import (
    RegisteredTool,
    RiskLevel,
    ToolCapabilities,
    ToolContext,
    ToolSpec,
)

_UNSAFE = re.compile(r"[^a-z0-9]+")
MAX_NAME_LENGTH = 64


def mcp_tool_name(server: str, tool: str) -> str:
    """Namespace an MCP tool so it can never shadow a built-in tool."""
    slug = _UNSAFE.sub("_", f"mcp_{server}_{tool}".casefold()).strip("_")
    if not slug or not slug[0].isalpha():
        slug = f"mcp_{slug}"
    return slug[:MAX_NAME_LENGTH].rstrip("_")


def mcp_capabilities(tool: McpTool) -> ToolCapabilities:
    """Decide what an MCP tool is allowed to do without trusting the server.

    MCP servers may advertise readOnlyHint/idempotentHint, but those come from
    the same third party that supplies the tool, so they are only ever used to
    raise the declared risk, never to lower it. Every MCP tool therefore
    reaches the permission gate as an approval-requiring action.
    """
    destructive = bool(tool.annotations.get("destructiveHint", False))
    open_world = bool(tool.annotations.get("openWorldHint", False))
    return ToolCapabilities(
        filesystem="workspace-write",
        network="unrestricted" if open_world else "deny",
        subprocess=True,
        risk_level=RiskLevel.CRITICAL if destructive else RiskLevel.HIGH,
        side_effects=True,
        idempotent=False,
    )


def make_mcp_tool(
    client: StdioMcpClient,
    server: str,
    tool: McpTool,
) -> RegisteredTool:
    async def handler(arguments, context: ToolContext) -> str:
        try:
            return await client.call_tool(tool.name, dict(arguments))
        except McpError as error:
            return f"mcp tool failed: {error}"

    description = tool.description or f"MCP tool '{tool.name}' from {server}"
    return RegisteredTool(
        ToolSpec(
            mcp_tool_name(server, tool.name),
            f"[mcp:{server}] {description}",
            dict(tool.input_schema),
            mcp_capabilities(tool),
        ),
        handler,
    )


async def register_mcp_tools(
    registry,
    client: StdioMcpClient,
    server: str,
) -> tuple[str, ...]:
    """Discover a server's tools and add them to the registry.

    Returns the registered names. A tool whose namespaced name collides with an
    existing one is skipped rather than allowed to replace it.
    """
    registered = []
    for tool in await client.list_tools():
        candidate = make_mcp_tool(client, server, tool)
        try:
            registry.register(candidate)
        except ValueError:
            continue
        registered.append(candidate.spec.name)
    return tuple(registered)

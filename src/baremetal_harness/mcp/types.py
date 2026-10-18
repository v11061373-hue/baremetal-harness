from dataclasses import dataclass


class McpError(RuntimeError):
    pass


class McpTimeout(McpError):
    pass


class McpServerClosed(McpError):
    pass


@dataclass(frozen=True, slots=True)
class McpTool:
    name: str
    description: str
    input_schema: dict[str, object]
    annotations: dict[str, object]


@dataclass(frozen=True, slots=True)
class McpServerInfo:
    name: str
    version: str
    protocol_version: str

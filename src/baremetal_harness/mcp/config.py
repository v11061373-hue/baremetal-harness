import json
from dataclasses import dataclass, field
from pathlib import Path

MCP_FILENAME = "mcp.json"


class McpConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class McpServerConfig:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    timeout: float = 30.0


def _parse(payload: object, source: Path) -> tuple[McpServerConfig, ...]:
    if not isinstance(payload, dict):
        raise McpConfigError(f"{source}: root must be an object")
    servers = payload.get("servers", payload.get("mcpServers"))
    if servers is None:
        return ()
    if not isinstance(servers, dict):
        raise McpConfigError(f"{source}: 'servers' must be an object")
    parsed = []
    for name, entry in sorted(servers.items()):
        if not isinstance(entry, dict):
            raise McpConfigError(f"{source}: server '{name}' must be an object")
        command = entry.get("command")
        if not isinstance(command, str) or not command:
            raise McpConfigError(f"{source}: server '{name}' needs a command")
        raw_args = entry.get("args", [])
        if not isinstance(raw_args, list) or not all(
            isinstance(item, str) for item in raw_args
        ):
            raise McpConfigError(f"{source}: server '{name}' args must be strings")
        raw_env = entry.get("env", {})
        if not isinstance(raw_env, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in raw_env.items()
        ):
            raise McpConfigError(f"{source}: server '{name}' env must be strings")
        parsed.append(
            McpServerConfig(
                name,
                command,
                tuple(raw_args),
                dict(raw_env),
                bool(entry.get("enabled", True)),
                float(entry.get("timeout", 30.0)),
            )
        )
    return tuple(parsed)


def load_mcp_servers(
    workspace: Path,
    *,
    user_root: Path | None = None,
) -> tuple[McpServerConfig, ...]:
    """Read MCP server definitions, project scope overriding user scope."""
    roots = (
        (user_root or Path.home() / ".baremetal_harness", "user"),
        (workspace / ".baremetal_harness", "project"),
    )
    by_name: dict[str, McpServerConfig] = {}
    for root, _scope in roots:
        path = root / MCP_FILENAME
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise McpConfigError(f"{path}: cannot be read as JSON") from error
        for server in _parse(payload, path):
            by_name[server.name] = server
    return tuple(by_name[name] for name in sorted(by_name))

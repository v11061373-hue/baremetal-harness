from baremetal_harness.tools.types import (
    RegisteredTool,
    ToolCapabilities,
    ToolContext,
    ToolSpec,
)
from baremetal_harness.workspace.paths import resolve_workspace_path


async def read_file(
    arguments: dict[str, object],
    context: ToolContext,
) -> str:
    path = resolve_workspace_path(context.workspace, str(arguments["path"]))
    return path.read_text()


async def write_file(
    arguments: dict[str, object],
    context: ToolContext,
) -> str:
    path = resolve_workspace_path(context.workspace, str(arguments["path"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(arguments["content"]))
    return f"wrote {path.relative_to(context.workspace)}"


def make_file_tools() -> tuple[RegisteredTool, ...]:
    closed_object = {"additionalProperties": False}
    return (
        RegisteredTool(
            ToolSpec(
                "read_file",
                "Read a UTF-8 text file inside the workspace",
                {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                    **closed_object,
                },
                ToolCapabilities(filesystem="read"),
            ),
            read_file,
        ),
        RegisteredTool(
            ToolSpec(
                "write_file",
                "Write a UTF-8 text file inside the workspace",
                {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                    **closed_object,
                },
                ToolCapabilities(
                    filesystem="workspace-write",
                    side_effects=True,
                    idempotent=True,
                ),
            ),
            write_file,
        ),
    )

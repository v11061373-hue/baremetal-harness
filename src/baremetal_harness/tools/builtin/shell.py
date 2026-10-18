import json
from collections.abc import Callable

from baremetal_harness.sandbox.process import ProcessSandbox
from baremetal_harness.sandbox.types import Command, SandboxPolicy, SandboxResult
from baremetal_harness.tools.types import (
    RegisteredTool,
    RiskLevel,
    ToolCapabilities,
    ToolContext,
    ToolSpec,
)


def make_run_command_tool(
    sandbox: ProcessSandbox,
    *,
    allowed_environment: tuple[str, ...] = ("PATH",),
    timeout_seconds: float = 30.0,
    max_output_bytes: int = 64 * 1024,
    result_sink: Callable[[SandboxResult], None] | None = None,
) -> RegisteredTool:
    async def run_command(
        arguments: dict[str, object],
        context: ToolContext,
    ) -> str:
        raw_argv = arguments["argv"]
        if not isinstance(raw_argv, list) or not all(
            isinstance(item, str) and item for item in raw_argv
        ):
            raise ValueError("argv must contain non-empty strings")
        result = await sandbox.execute(
            Command(tuple(raw_argv), context.workspace, {}),
            SandboxPolicy(
                context.workspace,
                "workspace-write",
                "deny",
                allowed_environment,
                timeout_seconds,
                max_output_bytes,
            ),
        )
        if result_sink is not None:
            result_sink(result)
        return json.dumps(
            {
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "changed_paths": [str(path) for path in result.changed_paths],
                "warnings": list(result.warnings),
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    return RegisteredTool(
        ToolSpec(
            "run_command",
            "Run an argv command in the bounded process sandbox",
            {
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
                "required": ["argv"],
                "additionalProperties": False,
            },
            ToolCapabilities(
                filesystem="workspace-write",
                subprocess=True,
                risk_level=RiskLevel.HIGH,
                side_effects=True,
                idempotent=False,
            ),
        ),
        run_command,
    )

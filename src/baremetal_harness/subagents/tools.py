import json

from baremetal_harness.subagents.runtime import SubagentRuntime
from baremetal_harness.subagents.types import SubagentSpec
from baremetal_harness.tools.types import (
    RegisteredTool,
    RiskLevel,
    ToolCapabilities,
    ToolContext,
    ToolSpec,
)


def make_delegate_tool(
    runtime: SubagentRuntime,
    *,
    parent_allowed_tools: tuple[str, ...],
    child_depth: int = 1,
) -> RegisteredTool:
    async def delegate_task(arguments, context: ToolContext) -> str:
        requested = tuple(str(item) for item in arguments["allowed_tools"])
        if set(requested) - set(parent_allowed_tools):
            raise ValueError("child requested a tool not allowed by parent")
        result = await runtime.spawn(
            SubagentSpec(
                str(arguments["agent_id"]),
                str(arguments["task"]),
                child_depth,
                int(arguments["max_turns"]),
                int(arguments.get("max_tool_calls", 4)),
                requested,
            )
        )
        return json.dumps(
            {
                "agent_id": result.agent_id,
                "status": result.status,
                "summary": result.summary,
                "evidence": list(result.evidence),
                "child_run_id": result.child_run_id,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    return RegisteredTool(
        ToolSpec(
            "delegate_task",
            "Delegate a bounded task to an isolated child agent",
            {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "task": {"type": "string"},
                    "max_turns": {"type": "integer"},
                    "max_tool_calls": {"type": "integer"},
                    "allowed_tools": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "agent_id",
                    "task",
                    "max_turns",
                    "allowed_tools",
                ],
                "additionalProperties": False,
            },
            ToolCapabilities(risk_level=RiskLevel.MEDIUM, side_effects=True),
        ),
        delegate_task,
    )

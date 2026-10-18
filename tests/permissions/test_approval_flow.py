from baremetal_harness.agent.loop import AgentLoop, ApprovalRequested, ApprovalResolved
from baremetal_harness.core.messages import ResponseCompleted, TextDelta, ToolCallDelta
from baremetal_harness.model.scripted import ScriptedModel
from baremetal_harness.permissions.approval import InMemoryApprovalProvider
from baremetal_harness.permissions.policy import DefaultPermissionPolicy
from baremetal_harness.permissions.types import PermissionRequest
from baremetal_harness.tools.registry import ToolRegistry
from baremetal_harness.tools.types import (
    RegisteredTool,
    RiskLevel,
    ToolCapabilities,
    ToolSpec,
)


async def test_approval_is_bound_to_one_request() -> None:
    provider = InMemoryApprovalProvider({"approval-1": True})
    request = PermissionRequest(
        "approval-1",
        "run-1",
        "call-1",
        "run_command",
        '{"argv":["python","-V"]}',
        ToolCapabilities(
            filesystem="workspace-write",
            subprocess=True,
            risk_level=RiskLevel.HIGH,
            side_effects=True,
            idempotent=False,
        ),
        "subprocess with side effects",
    )

    first = await provider.resolve(request)
    second = await provider.resolve(request)

    assert first.approved is True
    assert second.approved is False
    assert second.reason == "approval already consumed"


async def test_denied_tool_is_not_executed() -> None:
    calls = 0

    async def dangerous(arguments, context) -> str:
        nonlocal calls
        calls += 1
        return "executed"

    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            ToolSpec(
                "dangerous",
                "Dangerous action",
                {
                    "type": "object",
                    "properties": {},
                    "required": [],
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
            dangerous,
        )
    )
    provider = ScriptedModel(
        (
            (
                ToolCallDelta(0, "call-1", "dangerous", "{}"),
                ResponseCompleted("tool_calls"),
            ),
            (TextDelta("denied safely"), ResponseCompleted("stop")),
        )
    )
    loop = AgentLoop(
        provider,
        "fake",
        tools=registry,
        permission_policy=DefaultPermissionPolicy(),
        approval_provider=InMemoryApprovalProvider({}),
    )

    result = await loop.run("do it")

    assert calls == 0
    assert result.messages[2].content[0].is_error is True
    assert result.messages[2].content[0].output == "permission denied"
    assert any(isinstance(event.payload, ApprovalRequested) for event in result.events)
    assert any(isinstance(event.payload, ApprovalResolved) for event in result.events)

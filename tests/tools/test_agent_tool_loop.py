from baremetal_harness.agent.loop import AgentLoop
from baremetal_harness.agent.state import RunStatus
from baremetal_harness.core.messages import (
    ResponseCompleted,
    TextDelta,
    ToolCall,
    ToolCallDelta,
    ToolResultContent,
)
from baremetal_harness.model.scripted import ScriptedModel
from baremetal_harness.tools.registry import ToolRegistry
from baremetal_harness.tools.types import RegisteredTool, ToolCapabilities, ToolSpec


async def test_agent_executes_tool_once_and_continues() -> None:
    calls: list[str] = []

    async def echo(arguments, context) -> str:
        calls.append(str(arguments["text"]))
        return str(arguments["text"])

    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            ToolSpec(
                "echo",
                "Echo text",
                {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                    "additionalProperties": False,
                },
                ToolCapabilities(),
            ),
            echo,
        )
    )
    provider = ScriptedModel(
        (
            (
                ToolCallDelta(0, "call-1", "echo", '{"text":"hi"}'),
                ResponseCompleted("tool_calls"),
            ),
            (TextDelta("done"), ResponseCompleted("stop")),
        )
    )
    loop = AgentLoop(provider, "fake", tools=registry)

    result = await loop.run("use echo")

    assert result.status is RunStatus.COMPLETED
    assert result.output == "done"
    assert calls == ["hi"]
    second_request = provider.requests[1]
    assert any(
        isinstance(item, ToolCall)
        for message in second_request.messages
        for item in message.content
    )
    assert any(
        isinstance(item, ToolResultContent)
        for message in second_request.messages
        for item in message.content
    )

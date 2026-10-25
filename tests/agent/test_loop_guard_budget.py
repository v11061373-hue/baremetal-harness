from datetime import UTC, datetime, timedelta
from pathlib import Path

from baremetal_harness.agent.limits import RunLimits
from baremetal_harness.agent.loop import (
    AgentLoop,
    BudgetExceeded,
    PermissionEvaluated,
)
from baremetal_harness.agent.state import RunStatus
from baremetal_harness.core.events import EventEnvelope
from baremetal_harness.core.messages import ResponseCompleted, ToolCallDelta
from baremetal_harness.model.scripted import ScriptedModel
from baremetal_harness.sessions.events import JsonlEventStore
from baremetal_harness.tools.registry import ToolRegistry
from baremetal_harness.tools.types import RegisteredTool, ToolCapabilities, ToolSpec


async def test_permission_evaluated_roundtrips(tmp_path: Path) -> None:
    store = JsonlEventStore(tmp_path / "events.jsonl")
    envelope = EventEnvelope(
        "event-1", "run-1", "session-1", 1,
        datetime(2026, 7, 26, tzinfo=UTC),
        PermissionEvaluated("run_command", "deny", "destructive", "abc123"),
        None,
    )
    await store.append(envelope)
    (loaded,) = await store.load()
    assert loaded.payload == PermissionEvaluated(
        "run_command", "deny", "destructive", "abc123"
    )


async def test_budget_exceeded_roundtrips(tmp_path: Path) -> None:
    store = JsonlEventStore(tmp_path / "events.jsonl")
    envelope = EventEnvelope(
        "event-1", "run-1", "session-1", 1,
        datetime(2026, 7, 26, tzinfo=UTC),
        BudgetExceeded("turns"),
        None,
    )
    await store.append(envelope)
    (loaded,) = await store.load()
    assert loaded.payload == BudgetExceeded("turns")


def _echo_registry() -> ToolRegistry:
    async def echo(arguments, context) -> str:
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
    return registry


async def test_budget_exceeded_tool_calls_emitted() -> None:
    provider = ScriptedModel(
        ((ToolCallDelta(0, "call-1", "echo", '{"text":"hi"}'),
          ResponseCompleted("tool_calls")),)
    )
    loop = AgentLoop(
        provider, "fake", tools=_echo_registry(),
        limits=RunLimits(max_tool_calls=0),
    )
    result = await loop.run("use echo")
    assert result.status is RunStatus.EXHAUSTED
    assert any(
        isinstance(e.payload, BudgetExceeded) and e.payload.kind == "tool_calls"
        for e in result.events
    )


async def test_budget_exceeded_turns_emitted() -> None:
    provider = ScriptedModel(
        (
            (ToolCallDelta(0, "call-1", "echo", '{"text":"a"}'),
             ResponseCompleted("tool_calls")),
            (ToolCallDelta(0, "call-2", "echo", '{"text":"b"}'),
             ResponseCompleted("tool_calls")),
        )
    )
    loop = AgentLoop(
        provider, "fake", tools=_echo_registry(),
        limits=RunLimits(max_turns=2),
    )
    result = await loop.run("use echo")
    assert result.status is RunStatus.EXHAUSTED
    assert any(
        isinstance(e.payload, BudgetExceeded) and e.payload.kind == "turns"
        for e in result.events
    )


async def test_budget_exceeded_timeout_emitted() -> None:
    provider = ScriptedModel(
        (
            (ToolCallDelta(0, "call-1", "echo", '{"text":"a"}'),
             ResponseCompleted("tool_calls")),
            (ToolCallDelta(0, "call-2", "echo", '{"text":"b"}'),
             ResponseCompleted("tool_calls")),
        )
    )
    current = [datetime(2026, 1, 1, tzinfo=UTC)]
    def fake_clock() -> datetime:
        now = current[0]
        current[0] = now + timedelta(minutes=6)
        return now

    loop = AgentLoop(
        provider, "fake", tools=_echo_registry(),
        limits=RunLimits(max_turns=5, timeout_seconds=300.0),
        clock=fake_clock,
    )
    result = await loop.run("use echo")
    assert result.status is RunStatus.EXHAUSTED
    assert any(
        isinstance(e.payload, BudgetExceeded) and e.payload.kind == "timeout"
        for e in result.events
    )

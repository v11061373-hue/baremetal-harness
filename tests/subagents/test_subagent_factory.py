from pathlib import Path

import pytest

from baremetal_harness.core.errors import ToolNotFound
from baremetal_harness.core.messages import ResponseCompleted, TextDelta, ToolCallDelta
from baremetal_harness.model.scripted import ScriptedModel
from baremetal_harness.subagents.factory import AgentLoopFactory
from baremetal_harness.subagents.runtime import SubagentRuntime
from baremetal_harness.subagents.types import SubagentSpec
from baremetal_harness.tools.builtin.files import make_file_tools
from baremetal_harness.tools.registry import ToolRegistry
from baremetal_harness.tools.types import (
    RegisteredTool,
    ToolCapabilities,
    ToolContext,
    ToolSpec,
)


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in make_file_tools():
        registry.register(tool)
    return registry


def _factory(workspace: Path, provider: ScriptedModel) -> AgentLoopFactory:
    factory = AgentLoopFactory(provider, "test-model", workspace=workspace)
    factory.tools = _registry()
    return factory


async def test_child_runs_a_real_loop_and_reports_tool_evidence(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("child readable content")
    provider = ScriptedModel(
        (
            (
                ToolCallDelta(0, "call-1", "read_file", '{"path":"README.md"}'),
                ResponseCompleted("tool_calls"),
            ),
            (TextDelta("inspected the readme"), ResponseCompleted("stop")),
        )
    )

    result = await _factory(tmp_path, provider).run(
        SubagentSpec("reader", "inspect README", 1, 3, 3, ("read_file",))
    )

    assert result.status == "completed"
    assert result.summary == "inspected the readme"
    assert result.evidence == ("child readable content",)
    # A real child run, not a synthetic identifier.
    assert result.child_run_id and not result.child_run_id.startswith("child-")


async def test_child_registry_excludes_tools_outside_the_allowlist(
    tmp_path: Path,
) -> None:
    factory = _factory(tmp_path, ScriptedModel(()))

    tools = factory._child_tools(
        SubagentSpec("reader", "inspect", 1, 2, 2, ("read_file",))
    )

    assert tools.get("read_file") is not None
    with pytest.raises(ToolNotFound):
        tools.get("write_file")


async def test_child_cannot_call_a_tool_the_parent_withheld(
    tmp_path: Path,
) -> None:
    provider = ScriptedModel(
        (
            (
                ToolCallDelta(0, "call-1", "write_file", '{"path":"x","content":"y"}'),
                ResponseCompleted("tool_calls"),
            ),
            (TextDelta("done"), ResponseCompleted("stop")),
        )
    )

    result = await _factory(tmp_path, provider).run(
        SubagentSpec("reader", "try to write", 1, 3, 3, ("read_file",))
    )

    assert not (tmp_path / "x").exists()
    assert result.evidence == ()


async def test_child_turn_budget_is_enforced(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("content")
    provider = ScriptedModel(
        tuple(
            (
                ToolCallDelta(0, f"call-{index}", "read_file", '{"path":"README.md"}'),
                ResponseCompleted("tool_calls"),
            )
            for index in range(5)
        )
    )

    result = await _factory(tmp_path, provider).run(
        SubagentSpec("reader", "loop forever", 1, 2, 8, ("read_file",))
    )

    assert result.status == "exhausted"


async def test_delegate_depth_is_harness_controlled_not_model_controlled(
    tmp_path: Path,
) -> None:
    from baremetal_harness.subagents.tools import make_delegate_tool

    spawned: list[SubagentSpec] = []

    class RecordingFactory:
        async def run(self, spec: SubagentSpec):
            spawned.append(spec)
            from baremetal_harness.subagents.types import SubagentResult

            return SubagentResult(spec.agent_id, "completed", "ok", (), "run-1")

    runtime = SubagentRuntime(
        RecordingFactory(), max_depth=2, max_children=2
    )
    tool = make_delegate_tool(
        runtime, parent_allowed_tools=("read_file",), child_depth=2
    )

    # The model does not get to declare its own depth.
    assert "depth" not in tool.spec.parameters["properties"]
    await tool.handler(
        {
            "agent_id": "grandchild",
            "task": "dig deeper",
            "max_turns": 2,
            "allowed_tools": ["read_file"],
            "depth": 1,
        },
        ToolContext("run", "session", tmp_path),
    )

    assert spawned[0].depth == 2


async def test_child_beyond_max_depth_loses_the_delegate_tool(
    tmp_path: Path,
) -> None:
    factory = _factory(tmp_path, ScriptedModel(()))
    factory.tools.register(
        RegisteredTool(
            ToolSpec(
                "delegate_task",
                "delegate",
                {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                ToolCapabilities(),
            ),
            _noop_handler,
        )
    )
    factory.runtime = SubagentRuntime(factory, max_depth=2, max_children=2)

    at_limit = factory._child_tools(
        SubagentSpec("deep", "task", 2, 2, 2, ("read_file", "delegate_task"))
    )

    with pytest.raises(ToolNotFound):
        at_limit.get("delegate_task")


async def _noop_handler(arguments, context: ToolContext) -> str:
    return "noop"

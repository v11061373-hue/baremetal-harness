import asyncio

import pytest

from baremetal_harness.subagents.messages import AgentMessage, validate_message
from baremetal_harness.subagents.runtime import SubagentRuntime
from baremetal_harness.subagents.types import SubagentResult, SubagentSpec


class FakeFactory:
    def __init__(self) -> None:
        self.specs = []

    async def run(self, spec: SubagentSpec) -> SubagentResult:
        self.specs.append(spec)
        return SubagentResult(
            spec.agent_id,
            "completed",
            "done",
            ("file:a",),
            "run-child",
        )


def test_unknown_message_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="kind"):
        validate_message(AgentMessage("m1", "parent", "child", "secret", {}))


async def test_child_budget_does_not_mutate_parent_spec() -> None:
    factory = FakeFactory()
    runtime = SubagentRuntime(factory, max_depth=2, max_children=1)
    allowed = ("read_file",)
    spec = SubagentSpec("child", "inspect", 1, 2, 3, allowed)

    await runtime.spawn(spec)

    assert spec.allowed_tools == allowed
    assert factory.specs[0] is not spec


async def test_parent_cancellation_reaches_running_child() -> None:
    started = asyncio.Event()

    class BlockingFactory:
        async def run(self, spec: SubagentSpec) -> SubagentResult:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    runtime = SubagentRuntime(BlockingFactory(), max_depth=2, max_children=1)
    child = asyncio.create_task(
        runtime.spawn(SubagentSpec("child", "wait", 1, 2, 2, ()))
    )
    await started.wait()

    cancelled = await runtime.cancel_all()

    assert cancelled == 1
    with pytest.raises(asyncio.CancelledError):
        await child

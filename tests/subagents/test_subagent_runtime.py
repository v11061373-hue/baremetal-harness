import pytest

from baremetal_harness.subagents.runtime import SubagentLimitExceeded, SubagentRuntime
from baremetal_harness.subagents.types import SubagentResult, SubagentSpec


class FakeFactory:
    def __init__(self) -> None:
        self.specs = []

    async def run(self, spec: SubagentSpec) -> SubagentResult:
        self.specs.append(spec)
        return SubagentResult(spec.agent_id, "completed", "done", ("file:a",), "run-child")


async def test_runtime_rejects_depth_over_limit() -> None:
    runtime = SubagentRuntime(FakeFactory(), max_depth=2, max_children=3)
    spec = SubagentSpec("child", "inspect docs", 3, 4, 4, ("read_file",))

    with pytest.raises(SubagentLimitExceeded):
        await runtime.spawn(spec)


async def test_runtime_filters_tools_to_parent_allowlist() -> None:
    factory = FakeFactory()
    runtime = SubagentRuntime(
        factory,
        max_depth=2,
        max_children=3,
        parent_allowed_tools=("read_file",),
    )

    result = await runtime.spawn(
        SubagentSpec(
            "child",
            "inspect",
            1,
            4,
            4,
            ("read_file", "run_command"),
        )
    )

    assert result.summary == "done"
    assert factory.specs[0].allowed_tools == ("read_file",)

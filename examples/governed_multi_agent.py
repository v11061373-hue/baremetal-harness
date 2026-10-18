import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from baremetal_harness.permissions.approval import InMemoryApprovalProvider
from baremetal_harness.permissions.types import PermissionRequest
from baremetal_harness.scheduler.clock import FakeClock
from baremetal_harness.scheduler.runtime import SchedulerRuntime
from baremetal_harness.scheduler.store import SchedulerStore
from baremetal_harness.scheduler.types import (
    ScheduledTask,
    ScheduledTaskStatus,
    TaskRunResult,
)
from baremetal_harness.subagents.runtime import SubagentRuntime
from baremetal_harness.subagents.types import SubagentResult, SubagentSpec
from baremetal_harness.tools.types import RiskLevel, ToolCapabilities


async def main() -> None:
    class ChildFactory:
        async def run(self, spec: SubagentSpec) -> SubagentResult:
            return SubagentResult(
                spec.agent_id, "completed", "inspected", ("README.md",), "child-run"
            )

    child = await SubagentRuntime(
        ChildFactory(),
        max_depth=1,
        max_children=1,
        parent_allowed_tools=("read_file",),
    ).spawn(SubagentSpec("inspect", "inspect docs", 1, 2, 2, ("read_file",)))
    approval = InMemoryApprovalProvider({"approval-1": False})
    request = PermissionRequest(
        "approval-1",
        "run-parent",
        "call-risky",
        "run_command",
        "<redacted>",
        ToolCapabilities(
            filesystem="workspace-write",
            subprocess=True,
            risk_level=RiskLevel.HIGH,
            side_effects=True,
            idempotent=False,
        ),
        "high risk",
    )
    first = await approval.resolve(request)
    second = await approval.resolve(request)

    with tempfile.TemporaryDirectory() as temporary:
        now = datetime.now(UTC)
        store = SchedulerStore(Path(temporary) / "scheduler.db")
        await store.initialize()
        await store.add(ScheduledTask.once("parent", "cancel me", now))
        await store.add(
            ScheduledTask.once(
                "descendant", "child", now, parent_task_id="parent"
            )
        )
        await store.add(ScheduledTask.once("independent", "verify", now))
        cancelled = await store.cancel("parent")

        class Runner:
            async def run(self, task: ScheduledTask) -> TaskRunResult:
                return TaskRunResult("verify-run", True, None)

        await SchedulerRuntime(
            store, Runner(), FakeClock(now), max_concurrency=1
        ).tick()
        independent_done = (
            await store.get("independent")
        ).status is ScheduledTaskStatus.DONE

    print("delegated child completed:", "yes" if child.status == "completed" else "no")
    print("high-risk approval requested:", "yes")
    print(
        "approval reused:",
        "no" if not first.approved and second.reason == "approval already consumed" else "yes",
    )
    print("cancelled descendants:", max(cancelled - 1, 0))
    print("independent task completed:", "yes" if independent_done else "no")


if __name__ == "__main__":
    asyncio.run(main())

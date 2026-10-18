import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from baremetal_harness.planning.recovery import CompletedExecutionGuard
from baremetal_harness.planning.store import PlanStore
from baremetal_harness.planning.types import Plan, Task, TaskStatus
from baremetal_harness.sessions.checkpoints import FileCheckpointStore
from baremetal_harness.sessions.database import SessionRepository
from baremetal_harness.sessions.types import Checkpoint, RunRecord, SessionRecord


async def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        now = datetime.now(UTC)
        repository = SessionRepository(root / "state.db")
        await repository.initialize()
        await repository.create_session(SessionRecord("session-1", now, now))
        await repository.create_run(
            RunRecord("run-1", "session-1", "running", now, now)
        )
        checkpoints = FileCheckpointStore(root / "checkpoints", repository)
        plans = PlanStore(root / "plans.db")
        await plans.initialize()
        await plans.create(
            Plan(
                "plan-1",
                "update docs",
                (
                    Task("inspect", "Inspect files", (), TaskStatus.OPEN),
                    Task("edit", "Edit docs", ("inspect",), TaskStatus.OPEN),
                    Task("verify", "Run tests", ("edit",), TaskStatus.OPEN),
                ),
            )
        )
        await plans.transition("plan-1", "inspect", TaskStatus.IN_PROGRESS)
        await plans.transition("plan-1", "inspect", TaskStatus.DONE)
        await plans.transition("plan-1", "edit", TaskStatus.IN_PROGRESS)
        edit_count = 0

        async def edit() -> str:
            nonlocal edit_count
            edit_count += 1
            return "edited"

        guard = CompletedExecutionGuard(())
        await guard.execute("edit-execution", edit)
        await checkpoints.save(
            Checkpoint(
                "cp-edit",
                "run-1",
                "session-1",
                1,
                "recording_results",
                (),
                guard.completed_ids,
            )
        )
        await plans.transition(
            "plan-1",
            "edit",
            TaskStatus.DONE,
            evidence=("edit-execution",),
        )
        print("checkpoint saved after task: edit")
        print("simulated restart")

        recovered = await checkpoints.latest_for_run("run-1")
        restarted = CompletedExecutionGuard(recovered.completed_tool_executions)
        _, reused = await restarted.execute("edit-execution", edit)
        print("reused completed tool execution:", "yes" if reused else "no")
        await plans.transition("plan-1", "verify", TaskStatus.IN_PROGRESS)
        await plans.transition(
            "plan-1",
            "verify",
            TaskStatus.DONE,
            evidence=("tests passed",),
        )
        completed = all(
            task.status is TaskStatus.DONE
            for task in (await plans.get("plan-1")).tasks
        )
        print(
            "plan completed:",
            "yes" if completed and edit_count == 1 else "no",
        )


if __name__ == "__main__":
    asyncio.run(main())

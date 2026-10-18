from datetime import UTC, datetime
from pathlib import Path

from baremetal_harness.planning.recovery import CompletedExecutionGuard
from baremetal_harness.planning.store import PlanStore
from baremetal_harness.planning.types import Plan, Task, TaskStatus
from baremetal_harness.sessions.checkpoints import FileCheckpointStore
from baremetal_harness.sessions.database import SessionRepository
from baremetal_harness.sessions.types import Checkpoint, RunRecord, SessionRecord


async def test_completed_edit_is_not_repeated_after_restart(tmp_path: Path) -> None:
    now = datetime(2026, 7, 26, tzinfo=UTC)
    repository = SessionRepository(tmp_path / "state.db")
    await repository.initialize()
    await repository.create_session(SessionRecord("session-1", now, now))
    await repository.create_run(
        RunRecord("run-1", "session-1", "running", now, now)
    )
    checkpoints = FileCheckpointStore(tmp_path / "checkpoints", repository)
    store = PlanStore(tmp_path / "plans.db")
    await store.initialize()
    await store.create(
        Plan(
            "plan-1",
            "update docs",
            (
                Task("inspect", "Inspect", (), TaskStatus.OPEN),
                Task("edit", "Edit", ("inspect",), TaskStatus.OPEN),
                Task("verify", "Verify", ("edit",), TaskStatus.OPEN),
            ),
        )
    )
    await store.transition("plan-1", "inspect", TaskStatus.IN_PROGRESS)
    await store.transition("plan-1", "inspect", TaskStatus.DONE)
    await store.transition("plan-1", "edit", TaskStatus.IN_PROGRESS)
    calls = 0

    async def edit() -> str:
        nonlocal calls
        calls += 1
        return "edited"

    first = CompletedExecutionGuard(())
    assert await first.execute("edit-execution", edit) == ("edited", False)
    await checkpoints.save(
        Checkpoint(
            "cp-edit",
            "run-1",
            "session-1",
            1,
            "recording_results",
            (),
            first.completed_ids,
        )
    )
    await store.transition(
        "plan-1",
        "edit",
        TaskStatus.DONE,
        evidence=("edit-execution",),
    )

    recovered = await checkpoints.latest_for_run("run-1")
    restarted = CompletedExecutionGuard(recovered.completed_tool_executions)
    assert await restarted.execute("edit-execution", edit) == (None, True)
    await store.transition("plan-1", "verify", TaskStatus.IN_PROGRESS)
    await store.transition(
        "plan-1",
        "verify",
        TaskStatus.DONE,
        evidence=("tests passed",),
    )

    assert calls == 1
    assert all(
        task.status is TaskStatus.DONE
        for task in (await store.get("plan-1")).tasks
    )


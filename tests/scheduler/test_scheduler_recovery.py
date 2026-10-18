from datetime import UTC, datetime
from pathlib import Path

from baremetal_harness.scheduler.store import SchedulerStore
from baremetal_harness.scheduler.types import ScheduledTask, ScheduledTaskStatus


async def test_running_non_idempotent_requires_approval(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path / "scheduler.db")
    await store.initialize()
    task = ScheduledTask.once(
        "task-1",
        "deploy",
        datetime(2026, 7, 26, tzinfo=UTC),
        idempotent=False,
    )
    await store.add(task)
    await store.claim_due(task.run_at, 1)

    await store.recover_running(completed_child_runs=())

    assert (
        await store.get("task-1")
    ).status is ScheduledTaskStatus.APPROVAL_REQUIRED


async def test_cancel_recursively_cancels_descendants(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path / "scheduler.db")
    await store.initialize()
    now = datetime(2026, 7, 26, tzinfo=UTC)
    await store.add(ScheduledTask.once("parent", "parent", now))
    await store.add(
        ScheduledTask.once("child", "child", now, parent_task_id="parent")
    )

    cancelled = await store.cancel("parent")

    assert cancelled == 2
    assert (await store.get("child")).status is ScheduledTaskStatus.CANCELLED

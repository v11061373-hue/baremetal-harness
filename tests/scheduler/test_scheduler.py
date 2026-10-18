from datetime import UTC, datetime
from pathlib import Path

from baremetal_harness.scheduler.clock import FakeClock
from baremetal_harness.scheduler.runtime import SchedulerRuntime
from baremetal_harness.scheduler.store import SchedulerStore
from baremetal_harness.scheduler.types import (
    ScheduledTask,
    ScheduledTaskStatus,
    TaskRunResult,
)


class FakeRunner:
    def __init__(self) -> None:
        self.calls = []

    async def run(self, task: ScheduledTask) -> TaskRunResult:
        self.calls.append(task.task_id)
        return TaskRunResult("child-run", True, None)


async def test_due_task_runs_once(tmp_path: Path) -> None:
    clock = FakeClock(datetime(2026, 7, 26, tzinfo=UTC))
    store = SchedulerStore(tmp_path / "scheduler.db")
    await store.initialize()
    runner = FakeRunner()
    scheduler = SchedulerRuntime(store, runner, clock, max_concurrency=1)
    task = ScheduledTask.once("task-1", "inspect docs", run_at=clock.now())
    await store.add(task)

    await scheduler.tick()
    await scheduler.tick()

    assert runner.calls == ["task-1"]
    assert (await store.get("task-1")).status is ScheduledTaskStatus.DONE


async def test_claim_due_is_atomic(tmp_path: Path) -> None:
    now = datetime(2026, 7, 26, tzinfo=UTC)
    store = SchedulerStore(tmp_path / "scheduler.db")
    await store.initialize()
    await store.add(ScheduledTask.once("task-1", "inspect", now))

    first = await store.claim_due(now, 1)
    second = await store.claim_due(now, 1)

    assert [task.task_id for task in first] == ["task-1"]
    assert second == ()

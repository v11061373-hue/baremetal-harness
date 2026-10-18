import asyncio
import os
from typing import Protocol

from baremetal_harness.scheduler.store import SchedulerStore
from baremetal_harness.scheduler.types import ScheduledTask, TaskRunResult


class Clock(Protocol):
    def now(self): ...


class TaskRunner(Protocol):
    async def run(self, task: ScheduledTask) -> TaskRunResult: ...


class SchedulerRuntime:
    def __init__(
        self,
        store: SchedulerStore,
        runner: TaskRunner,
        clock: Clock,
        *,
        max_concurrency: int,
        owner: str | None = None,
    ) -> None:
        self.store = store
        self.runner = runner
        self.clock = clock
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.max_concurrency = max_concurrency
        # Identifies which process holds a claimed task, so a stuck runner can
        # be told apart from one that simply has not finished yet.
        self.owner = owner or f"pid-{os.getpid()}"

    async def tick(self) -> None:
        tasks = await self.store.claim_due(
            self.clock.now(),
            self.max_concurrency,
            owner=self.owner,
        )
        await asyncio.gather(*(self._run(task) for task in tasks))

    async def _run(self, task: ScheduledTask) -> None:
        async with self.semaphore:
            try:
                result = await self.runner.run(task)
            except Exception:
                await self.store.finish(
                    task.task_id,
                    child_run_id="",
                    succeeded=False,
                    error="scheduled task failed",
                )
                return
            await self.store.finish(
                task.task_id,
                child_run_id=result.child_run_id,
                succeeded=result.succeeded,
                error=result.error,
            )

    async def run_forever(self, poll_interval: float) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(poll_interval)

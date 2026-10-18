from pathlib import Path

from baremetal_harness.planning.store import PlanStore
from baremetal_harness.planning.types import Plan, Task, TaskStatus, TodoStatus


async def test_store_keeps_task_and_todo_in_sync(tmp_path: Path) -> None:
    path = tmp_path / "plans.db"
    store = PlanStore(path)
    await store.initialize()
    await store.create(
        Plan(
            "plan-1",
            "update docs",
            (Task("inspect", "Inspect", (), TaskStatus.OPEN),),
        )
    )

    await store.transition("plan-1", "inspect", TaskStatus.IN_PROGRESS)
    reopened = PlanStore(path)
    plan = await reopened.get("plan-1")
    todos = await reopened.list_todos("plan-1")

    assert plan.tasks[0].status is TaskStatus.IN_PROGRESS
    assert plan.tasks[0].attempts == 1
    assert todos[0].status is TodoStatus.IN_PROGRESS

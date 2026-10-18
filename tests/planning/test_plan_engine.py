import pytest

from baremetal_harness.planning.engine import PlanEngine, PlanInvariantError
from baremetal_harness.planning.store import PlanStore
from baremetal_harness.planning.tools import make_planning_tools
from baremetal_harness.planning.types import Plan, Task, TaskStatus


def test_next_runnable_respects_dependencies() -> None:
    plan = Plan(
        plan_id="plan-1",
        goal="update docs",
        tasks=(
            Task("inspect", "Inspect files", (), TaskStatus.DONE),
            Task("edit", "Edit README", ("inspect",), TaskStatus.OPEN),
            Task("verify", "Run checks", ("edit",), TaskStatus.OPEN),
        ),
    )

    assert PlanEngine().next_runnable(plan).task_id == "edit"


def test_plan_rejects_missing_dependency() -> None:
    plan = Plan(
        "plan-1",
        "broken",
        (Task("edit", "Edit", ("missing",), TaskStatus.OPEN),),
    )

    with pytest.raises(PlanInvariantError, match="missing"):
        PlanEngine().validate(plan)


def test_failed_task_blocks_after_attempt_budget() -> None:
    engine = PlanEngine()
    task = Task("edit", "Edit", (), TaskStatus.OPEN, max_attempts=1)

    started = engine.transition(task, TaskStatus.IN_PROGRESS)
    blocked = engine.transition(started, TaskStatus.FAILED)

    assert blocked.status is TaskStatus.BLOCKED
    assert blocked.attempts == 1


def test_planning_tool_catalog_is_complete(tmp_path) -> None:
    tools = make_planning_tools(PlanStore(tmp_path / "plans.db"))

    assert {tool.spec.name for tool in tools} == {
        "create_plan",
        "list_tasks",
        "list_todos",
        "start_task",
        "complete_task",
        "fail_task",
    }


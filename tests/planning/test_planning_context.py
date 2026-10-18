from pathlib import Path

from baremetal_harness.planning.context import plan_context_source
from baremetal_harness.planning.store import PlanStore
from baremetal_harness.planning.types import Plan, Task, TaskStatus


async def test_context_contains_goal_current_and_recent_evidence(
    tmp_path: Path,
) -> None:
    store = PlanStore(tmp_path / "plans.db")
    await store.initialize()
    await store.create(
        Plan(
            "plan-1",
            "ship release",
            (
                Task(
                    "inspect",
                    "Inspect",
                    (),
                    TaskStatus.DONE,
                    evidence=("files listed",),
                ),
                Task("edit", "Edit", ("inspect",), TaskStatus.OPEN),
            ),
        )
    )

    source = plan_context_source(await store.get("plan-1"))

    assert source.source_id == "plan"
    assert "ship release" in source.text
    assert "edit: Edit" in source.text
    assert "files listed" in source.text

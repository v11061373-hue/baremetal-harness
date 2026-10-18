from baremetal_harness.context.builder import DEFAULT_CONTEXT_PRIORITIES
from baremetal_harness.context.types import ContextSource
from baremetal_harness.planning.engine import PlanEngine
from baremetal_harness.planning.types import Plan, TaskStatus


def plan_context_source(plan: Plan) -> ContextSource:
    runnable = PlanEngine().next_runnable(plan)
    blocked = [task for task in plan.tasks if task.status is TaskStatus.BLOCKED]
    completed = [
        task for task in plan.tasks if task.status is TaskStatus.DONE
    ][-5:]
    lines = [f"Goal: {plan.goal}"]
    if runnable is not None:
        lines.append(f"Current: {runnable.task_id}: {runnable.title}")
    if blocked:
        lines.append(
            "Blocked: "
            + ", ".join(f"{task.task_id}: {task.title}" for task in blocked)
        )
    for task in completed:
        lines.append(
            f"Completed: {task.task_id}: {task.title}; "
            f"evidence={'; '.join(task.evidence) or 'none'}"
        )
    return ContextSource(
        "plan",
        "\n".join(lines),
        DEFAULT_CONTEXT_PRIORITIES["plan"],
    )

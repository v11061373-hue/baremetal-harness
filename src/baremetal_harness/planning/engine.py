from dataclasses import replace

from baremetal_harness.planning.types import Plan, Task, TaskStatus


class PlanInvariantError(ValueError):
    pass


class PlanTransitionError(ValueError):
    pass


_TRANSITIONS = {
    TaskStatus.OPEN: {TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED},
    TaskStatus.IN_PROGRESS: {
        TaskStatus.DONE,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.FAILED: {TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED},
}


class PlanEngine:
    def validate(self, plan: Plan) -> None:
        identifiers = [task.task_id for task in plan.tasks]
        if len(identifiers) != len(set(identifiers)):
            raise PlanInvariantError("duplicate task id")
        known = set(identifiers)
        for task in plan.tasks:
            missing = set(task.depends_on) - known
            if missing:
                raise PlanInvariantError(
                    f"missing dependencies: {', '.join(sorted(missing))}"
                )
        visiting: set[str] = set()
        visited: set[str] = set()
        by_id = {task.task_id: task for task in plan.tasks}

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise PlanInvariantError("dependency cycle")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in by_id[task_id].depends_on:
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in identifiers:
            visit(task_id)

    def next_runnable(self, plan: Plan) -> Task | None:
        self.validate(plan)
        by_id = {task.task_id: task for task in plan.tasks}
        for task in plan.tasks:
            if task.status is TaskStatus.OPEN and all(
                by_id[dependency].status is TaskStatus.DONE
                for dependency in task.depends_on
            ):
                return task
        return None

    def transition(
        self,
        task: Task,
        target: TaskStatus,
        *,
        evidence: tuple[str, ...] = (),
    ) -> Task:
        if target not in _TRANSITIONS.get(task.status, set()):
            raise PlanTransitionError(
                f"illegal task transition: {task.status} -> {target}"
            )
        attempts = task.attempts
        if target is TaskStatus.IN_PROGRESS:
            attempts += 1
        if target is TaskStatus.FAILED and attempts >= task.max_attempts:
            target = TaskStatus.BLOCKED
        return replace(
            task,
            status=target,
            attempts=attempts,
            evidence=task.evidence + evidence,
        )

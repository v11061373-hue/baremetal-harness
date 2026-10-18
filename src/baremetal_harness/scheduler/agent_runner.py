from baremetal_harness.agent.state import RunStatus
from baremetal_harness.scheduler.types import ScheduledTask, TaskRunResult


class AgentTaskRunner:
    """Execute a scheduled task as a real, isolated agent run.

    A scheduled task runs unattended, so it never inherits the interactive
    conversation: it starts from an empty history and reports only the run
    identifier and outcome back to the scheduler.
    """

    def __init__(self, agent) -> None:
        self.agent = agent

    async def run(self, task: ScheduledTask) -> TaskRunResult:
        result = await self.agent.run(_task_prompt(task))
        if result.status is RunStatus.COMPLETED:
            return TaskRunResult(result.run_id, True, None)
        return TaskRunResult(
            result.run_id,
            False,
            f"scheduled run ended with status {result.status.value}",
        )


def _task_prompt(task: ScheduledTask) -> str:
    return (
        f"You are running scheduled task '{task.task_id}' without a user present.\n"
        f"Task: {task.task_text}\n"
        "Complete it and summarize what changed."
    )

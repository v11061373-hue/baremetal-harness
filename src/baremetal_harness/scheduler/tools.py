import json
from datetime import datetime

from baremetal_harness.scheduler.store import SchedulerStore
from baremetal_harness.scheduler.types import ScheduledTask
from baremetal_harness.tools.types import (
    RegisteredTool,
    RiskLevel,
    ToolCapabilities,
    ToolContext,
    ToolSpec,
)


def make_scheduler_tools(store: SchedulerStore) -> tuple[RegisteredTool, ...]:
    async def schedule_task(arguments, context: ToolContext) -> str:
        task = ScheduledTask.once(
            str(arguments["task_id"]),
            str(arguments["task"]),
            datetime.fromisoformat(str(arguments["run_at"])),
            idempotent=bool(arguments["idempotent"]),
            parent_task_id=(
                str(arguments["parent_task_id"])
                if arguments.get("parent_task_id") is not None
                else None
            ),
        )
        await store.add(task)
        return task.task_id

    async def list_scheduled_tasks(arguments, context: ToolContext) -> str:
        return json.dumps(
            [
                {
                    "task_id": task.task_id,
                    "status": task.status.value,
                    "child_run_id": task.child_run_id,
                }
                for task in await store.list()
            ],
            separators=(",", ":"),
        )

    async def cancel_scheduled_task(arguments, context: ToolContext) -> str:
        return str(await store.cancel(str(arguments["task_id"])))

    async def get_scheduled_task(arguments, context: ToolContext) -> str:
        task = await store.get(str(arguments["task_id"]))
        return json.dumps(
            {
                "task_id": task.task_id,
                "task": task.task_text,
                "status": task.status.value,
                "attempts": task.attempts,
                "child_run_id": task.child_run_id,
            },
            separators=(",", ":"),
        )

    no_arguments = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }
    task_id = {
        "type": "object",
        "properties": {"task_id": {"type": "string"}},
        "required": ["task_id"],
        "additionalProperties": False,
    }
    definitions = (
        (
            "schedule_task",
            "Schedule a durable background task",
            {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "task": {"type": "string"},
                    "run_at": {"type": "string"},
                    "idempotent": {"type": "boolean"},
                    "parent_task_id": {"type": "string"},
                },
                "required": ["task_id", "task", "run_at", "idempotent"],
                "additionalProperties": False,
            },
            schedule_task,
            ToolCapabilities(
                risk_level=RiskLevel.HIGH,
                side_effects=True,
                idempotent=False,
            ),
        ),
        (
            "list_scheduled_tasks",
            "List durable background tasks",
            no_arguments,
            list_scheduled_tasks,
            ToolCapabilities(),
        ),
        (
            "cancel_scheduled_task",
            "Cancel a task and descendants",
            task_id,
            cancel_scheduled_task,
            ToolCapabilities(side_effects=True),
        ),
        (
            "get_scheduled_task",
            "Get one background task",
            task_id,
            get_scheduled_task,
            ToolCapabilities(),
        ),
    )
    return tuple(
        RegisteredTool(ToolSpec(name, description, schema, capabilities), handler)
        for name, description, schema, handler, capabilities in definitions
    )

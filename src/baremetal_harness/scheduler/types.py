from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ScheduledTaskStatus(StrEnum):
    SCHEDULED = "scheduled"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    APPROVAL_REQUIRED = "approval_required"


@dataclass(frozen=True, slots=True)
class ScheduledTask:
    task_id: str
    task_text: str
    run_at: datetime
    status: ScheduledTaskStatus
    attempts: int
    max_attempts: int
    idempotent: bool
    parent_task_id: str | None = None
    child_run_id: str | None = None
    last_error: str | None = None

    @classmethod
    def once(
        cls,
        task_id: str,
        task_text: str,
        run_at: datetime,
        *,
        idempotent: bool = True,
        max_attempts: int = 1,
        parent_task_id: str | None = None,
    ) -> "ScheduledTask":
        return cls(
            task_id,
            task_text,
            run_at,
            ScheduledTaskStatus.SCHEDULED,
            0,
            max_attempts,
            idempotent,
            parent_task_id,
        )


@dataclass(frozen=True, slots=True)
class TaskRunResult:
    child_run_id: str
    succeeded: bool
    error: str | None

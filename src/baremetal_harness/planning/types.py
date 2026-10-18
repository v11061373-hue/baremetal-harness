from dataclasses import dataclass
from enum import StrEnum


class TaskStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class TodoStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    title: str
    depends_on: tuple[str, ...]
    status: TaskStatus
    attempts: int = 0
    max_attempts: int = 1
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Plan:
    plan_id: str
    goal: str
    tasks: tuple[Task, ...]


@dataclass(frozen=True, slots=True)
class Todo:
    todo_id: str
    plan_id: str
    task_id: str
    title: str
    status: TodoStatus
    priority: int

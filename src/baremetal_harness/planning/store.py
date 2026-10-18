import asyncio
import json
import sqlite3
from pathlib import Path

from baremetal_harness.planning.engine import PlanEngine
from baremetal_harness.planning.types import (
    Plan,
    Task,
    TaskStatus,
    Todo,
    TodoStatus,
)

_TODO_STATUS = {
    TaskStatus.OPEN: TodoStatus.OPEN,
    TaskStatus.IN_PROGRESS: TodoStatus.IN_PROGRESS,
    TaskStatus.DONE: TodoStatus.DONE,
    TaskStatus.FAILED: TodoStatus.BLOCKED,
    TaskStatus.BLOCKED: TodoStatus.BLOCKED,
    TaskStatus.CANCELLED: TodoStatus.CANCELLED,
}


class PlanStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.engine = PlanEngine()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    async def initialize(self) -> None:
        return await asyncio.to_thread(self._initialize_blocking)

    def _initialize_blocking(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    plan_id TEXT NOT NULL REFERENCES plans(plan_id),
                    task_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    depends_on_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    evidence_json TEXT NOT NULL,
                    PRIMARY KEY (plan_id, task_id)
                );
                CREATE TABLE IF NOT EXISTS todos (
                    todo_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    FOREIGN KEY (plan_id, task_id)
                        REFERENCES tasks(plan_id, task_id)
                );
                """
            )

    async def create(self, plan: Plan) -> None:
        return await asyncio.to_thread(self._create_blocking, plan)

    def _create_blocking(self, plan: Plan) -> None:
        self.engine.validate(plan)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO plans VALUES (?, ?)",
                (plan.plan_id, plan.goal),
            )
            for priority, task in enumerate(plan.tasks):
                connection.execute(
                    "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        plan.plan_id,
                        task.task_id,
                        task.title,
                        json.dumps(task.depends_on),
                        task.status.value,
                        task.attempts,
                        task.max_attempts,
                        json.dumps(task.evidence),
                    ),
                )
                connection.execute(
                    "INSERT INTO todos VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        task.task_id,
                        plan.plan_id,
                        task.task_id,
                        task.title,
                        _TODO_STATUS[task.status].value,
                        priority,
                    ),
                )
            connection.commit()

    async def get(self, plan_id: str) -> Plan:
        return await asyncio.to_thread(self._get_blocking, plan_id)

    def _get_blocking(self, plan_id: str) -> Plan:
        with self._connect() as connection:
            plan_row = connection.execute(
                "SELECT * FROM plans WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
            task_rows = connection.execute(
                "SELECT * FROM tasks WHERE plan_id = ? ORDER BY rowid",
                (plan_id,),
            ).fetchall()
        if plan_row is None:
            raise KeyError(plan_id)
        return Plan(
            plan_row["plan_id"],
            plan_row["goal"],
            tuple(self._decode_task(row) for row in task_rows),
        )

    async def list_todos(self, plan_id: str) -> tuple[Todo, ...]:
        return await asyncio.to_thread(self._list_todos_blocking, plan_id)

    def _list_todos_blocking(self, plan_id: str) -> tuple[Todo, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM todos WHERE plan_id = ? ORDER BY priority",
                (plan_id,),
            ).fetchall()
        return tuple(
            Todo(
                row["todo_id"],
                row["plan_id"],
                row["task_id"],
                row["title"],
                TodoStatus(row["status"]),
                row["priority"],
            )
            for row in rows
        )

    async def list_tasks(self) -> tuple[tuple[str, Task], ...]:
        return await asyncio.to_thread(self._list_tasks_blocking)

    def _list_tasks_blocking(self) -> tuple[tuple[str, Task], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks ORDER BY rowid"
            ).fetchall()
        return tuple(
            (row["plan_id"], self._decode_task(row))
            for row in rows
        )

    async def transition(
        self,
        plan_id: str,
        task_id: str,
        target: TaskStatus,
        *,
        evidence: tuple[str, ...] = (),
    ) -> Task:
        plan = await self.get(plan_id)
        current = next(task for task in plan.tasks if task.task_id == task_id)
        updated = self.engine.transition(current, target, evidence=evidence)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE tasks
                SET status = ?, attempts = ?, evidence_json = ?
                WHERE plan_id = ? AND task_id = ?
                """,
                (
                    updated.status.value,
                    updated.attempts,
                    json.dumps(updated.evidence),
                    plan_id,
                    task_id,
                ),
            )
            connection.execute(
                """
                UPDATE todos SET status = ?
                WHERE plan_id = ? AND task_id = ?
                """,
                (_TODO_STATUS[updated.status].value, plan_id, task_id),
            )
            connection.commit()
        return updated

    @staticmethod
    def _decode_task(row: sqlite3.Row) -> Task:
        return Task(
            row["task_id"],
            row["title"],
            tuple(json.loads(row["depends_on_json"])),
            TaskStatus(row["status"]),
            row["attempts"],
            row["max_attempts"],
            tuple(json.loads(row["evidence_json"])),
        )

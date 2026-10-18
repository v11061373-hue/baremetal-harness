import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path

from baremetal_harness.scheduler.types import ScheduledTask, ScheduledTaskStatus


class SchedulerStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    async def initialize(self) -> None:
        return await asyncio.to_thread(self._initialize_blocking)

    def _initialize_blocking(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    task_id TEXT PRIMARY KEY,
                    task_text TEXT NOT NULL,
                    run_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    idempotent INTEGER NOT NULL,
                    parent_task_id TEXT,
                    child_run_id TEXT,
                    last_error TEXT
                )
                """
            )
            # Added after the original schema; existing databases keep working.
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(scheduled_tasks)"
                ).fetchall()
            }
            if "owner" not in columns:
                connection.execute(
                    "ALTER TABLE scheduled_tasks ADD COLUMN owner TEXT"
                )

    async def add(self, task: ScheduledTask) -> None:
        return await asyncio.to_thread(self._add_blocking, task)

    def _add_blocking(self, task: ScheduledTask) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO scheduled_tasks (
                    task_id, task_text, run_at, status, attempts,
                    max_attempts, idempotent, parent_task_id,
                    child_run_id, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.task_text,
                    task.run_at.isoformat(),
                    task.status.value,
                    task.attempts,
                    task.max_attempts,
                    int(task.idempotent),
                    task.parent_task_id,
                    task.child_run_id,
                    task.last_error,
                ),
            )

    async def get(self, task_id: str) -> ScheduledTask:
        return await asyncio.to_thread(self._get_blocking, task_id)

    def _get_blocking(self, task_id: str) -> ScheduledTask:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._decode(row)

    async def list(self) -> tuple[ScheduledTask, ...]:
        return await asyncio.to_thread(self._list_blocking)

    def _list_blocking(self) -> tuple[ScheduledTask, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM scheduled_tasks ORDER BY run_at, task_id"
            ).fetchall()
        return tuple(self._decode(row) for row in rows)

    async def claim_due(
        self,
        now: datetime,
        limit: int,
        *,
        owner: str | None = None,
    ) -> tuple[ScheduledTask, ...]:
        return await asyncio.to_thread(
            self._claim_due_blocking, now, limit, owner=owner
        )

    def _claim_due_blocking(
        self,
        now: datetime,
        limit: int,
        *,
        owner: str | None = None,
    ) -> tuple[ScheduledTask, ...]:
        # BEGIN IMMEDIATE takes SQLite's write lock before the SELECT, so two
        # processes polling the same database cannot both claim one task: the
        # loser blocks, then sees the row already marked running.
        # BEGIN IMMEDIATE takes SQLite's write lock before the SELECT, so two
        # processes polling the same database cannot both claim one task: the
        # loser blocks, then sees the row already marked running.
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM scheduled_tasks
                WHERE status = ? AND run_at <= ?
                ORDER BY run_at, task_id
                LIMIT ?
                """,
                (ScheduledTaskStatus.SCHEDULED.value, now.isoformat(), limit),
            ).fetchall()
            identifiers = [row["task_id"] for row in rows]
            claimed = []
            for task_id in identifiers:
                cursor = connection.execute(
                    """
                    UPDATE scheduled_tasks
                    SET status = ?, attempts = attempts + 1, owner = ?
                    WHERE task_id = ? AND status = ?
                    """,
                    (
                        ScheduledTaskStatus.RUNNING.value,
                        owner,
                        task_id,
                        ScheduledTaskStatus.SCHEDULED.value,
                    ),
                )
                if cursor.rowcount:
                    claimed.append(task_id)
            connection.commit()
        rows = [row for row in rows if row["task_id"] in set(claimed)]
        return tuple(
            ScheduledTask(
                row["task_id"],
                row["task_text"],
                datetime.fromisoformat(row["run_at"]),
                ScheduledTaskStatus.RUNNING,
                row["attempts"] + 1,
                row["max_attempts"],
                bool(row["idempotent"]),
                row["parent_task_id"],
                row["child_run_id"],
                row["last_error"],
            )
            for row in rows
        )

    async def finish(
        self,
        task_id: str,
        *,
        child_run_id: str,
        succeeded: bool,
        error: str | None,
    ) -> None:
        task = await self.get(task_id)
        if succeeded:
            status = ScheduledTaskStatus.DONE
        elif task.idempotent and task.attempts < task.max_attempts:
            status = ScheduledTaskStatus.SCHEDULED
        else:
            status = ScheduledTaskStatus.FAILED
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE scheduled_tasks
                SET status = ?, child_run_id = ?, last_error = ?
                WHERE task_id = ?
                """,
                (status.value, child_run_id, error, task_id),
            )

    async def recover_running(
        self,
        *,
        completed_child_runs: tuple[str, ...],
    ) -> None:
        return await asyncio.to_thread(
            self._recover_running_blocking,
            completed_child_runs=completed_child_runs,
        )

    def _recover_running_blocking(
        self,
        *,
        completed_child_runs: tuple[str, ...],
    ) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT * FROM scheduled_tasks WHERE status = ?",
                (ScheduledTaskStatus.RUNNING.value,),
            ).fetchall()
            for row in rows:
                if row["child_run_id"] in completed_child_runs:
                    status = ScheduledTaskStatus.DONE
                elif bool(row["idempotent"]):
                    status = ScheduledTaskStatus.SCHEDULED
                else:
                    status = ScheduledTaskStatus.APPROVAL_REQUIRED
                connection.execute(
                    "UPDATE scheduled_tasks SET status = ? WHERE task_id = ?",
                    (status.value, row["task_id"]),
                )
            connection.commit()

    async def cancel(self, task_id: str) -> int:
        return await asyncio.to_thread(self._cancel_blocking, task_id)

    def _cancel_blocking(self, task_id: str) -> int:
        cancelled = 0
        pending = [task_id]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            while pending:
                current = pending.pop()
                children = connection.execute(
                    "SELECT task_id FROM scheduled_tasks WHERE parent_task_id = ?",
                    (current,),
                ).fetchall()
                pending.extend(row["task_id"] for row in children)
                cursor = connection.execute(
                    """
                    UPDATE scheduled_tasks SET status = ?
                    WHERE task_id = ? AND status NOT IN (?, ?, ?)
                    """,
                    (
                        ScheduledTaskStatus.CANCELLED.value,
                        current,
                        ScheduledTaskStatus.DONE.value,
                        ScheduledTaskStatus.FAILED.value,
                        ScheduledTaskStatus.CANCELLED.value,
                    ),
                )
                cancelled += cursor.rowcount
            connection.commit()
        return cancelled

    @staticmethod
    def _decode(row: sqlite3.Row) -> ScheduledTask:
        return ScheduledTask(
            row["task_id"],
            row["task_text"],
            datetime.fromisoformat(row["run_at"]),
            ScheduledTaskStatus(row["status"]),
            row["attempts"],
            row["max_attempts"],
            bool(row["idempotent"]),
            row["parent_task_id"],
            row["child_run_id"],
            row["last_error"],
        )

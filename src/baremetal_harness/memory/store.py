import asyncio
import hashlib
import json
import re
import sqlite3
from pathlib import Path

from baremetal_harness.memory.search import memory_score, normalize
from baremetal_harness.memory.types import MemoryRecord


class MemorySourceRejected(ValueError):
    pass


class SqliteMemoryStore:
    def __init__(
        self,
        database_path: Path,
        source_directory: Path,
        *,
        secret_patterns: tuple[str, ...] = (),
    ) -> None:
        self.database_path = database_path
        self.source_directory = source_directory
        self.secret_patterns = tuple(re.compile(pattern) for pattern in secret_patterns)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    async def initialize(self) -> None:
        return await asyncio.to_thread(self._initialize_blocking)

    def _initialize_blocking(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.source_directory.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    normalized_text TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    supersedes TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_memories_normalized
                    ON memories(normalized_text);
                """
            )

    async def put(self, memory: MemoryRecord) -> None:
        return await asyncio.to_thread(self._put_blocking, memory)

    def _put_blocking(self, memory: MemoryRecord) -> None:
        if not memory.source_ref:
            raise ValueError("memory source_ref is required")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    memory.memory_id,
                    memory.text,
                    normalize(memory.text),
                    memory.source_ref,
                    json.dumps(memory.tags, separators=(",", ":")),
                    memory.created_at,
                    memory.supersedes,
                ),
            )

    async def put_with_source(
        self,
        *,
        memory_id: str,
        text: str,
        source_content: str,
        tags: tuple[str, ...],
        created_at: str,
        supersedes: str | None = None,
    ) -> MemoryRecord:
        if any(pattern.search(source_content) for pattern in self.secret_patterns):
            raise MemorySourceRejected("source matches a configured secret pattern")
        if len(source_content.encode()) > 4096:
            digest = hashlib.sha256(source_content.encode()).hexdigest()
            path = self.source_directory / f"{digest}.txt"
            if not path.exists():
                path.write_text(source_content)
            source_ref = f"file:{digest}"
        else:
            digest = hashlib.sha256(source_content.encode()).hexdigest()
            source_ref = f"inline-sha256:{digest}"
        memory = MemoryRecord(
            memory_id,
            text,
            source_ref,
            tags,
            created_at,
            supersedes,
        )
        await self.put(memory)
        return memory

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> tuple[MemoryRecord, ...]:
        return await asyncio.to_thread(self._search_blocking, query, limit=limit)

    def _search_blocking(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> tuple[MemoryRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM memories").fetchall()
        records = tuple(
            MemoryRecord(
                row["memory_id"],
                row["text"],
                row["source_ref"],
                tuple(json.loads(row["tags_json"])),
                row["created_at"],
                row["supersedes"],
            )
            for row in rows
        )
        scored = [
            (memory_score(record, query), record)
            for record in records
            if memory_score(record, query) > 0
        ]
        scored.sort(
            key=lambda item: (
                item[0],
                item[1].created_at,
                item[1].memory_id,
            ),
            reverse=True,
        )
        return tuple(record for _, record in scored[:limit])

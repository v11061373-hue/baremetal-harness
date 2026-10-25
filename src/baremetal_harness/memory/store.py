import asyncio
import hashlib
import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from baremetal_harness.memory.consolidation import (
    ConsolidationAction,
    MemoryCandidate,
    MemoryConsolidator,
)
from baremetal_harness.memory.search import BM25, normalize
from baremetal_harness.memory.types import MemoryRecord


class MemorySourceRejected(ValueError):
    pass


CATEGORY_HALF_LIVES = {
    "strategy": 38.0,
    "fact": 24.0,
    "assumption": 19.0,
    "failure": 11.0,
}
DEFAULT_HALF_LIFE_DAYS = 30.0
PRUNE_STRENGTH = 0.05
OUTCOME_FAILED_TAG = "outcome:failed"


def _category_half_life(record: MemoryRecord) -> float:
    for tag in record.tags:
        if tag.startswith("category:"):
            return CATEGORY_HALF_LIVES.get(
                tag.removeprefix("category:"), DEFAULT_HALF_LIFE_DAYS
            )
    if OUTCOME_FAILED_TAG in record.tags:
        return CATEGORY_HALF_LIVES["failure"]
    return DEFAULT_HALF_LIFE_DAYS


def _strength(record: MemoryRecord, now: datetime) -> float:
    try:
        created = datetime.fromisoformat(record.created_at)
    except ValueError:
        return 1.0
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    age_days = max(0.0, (now - created).total_seconds() / 86400.0)
    return 0.5 ** (age_days / _category_half_life(record))


def _outcome_boost(record: MemoryRecord) -> float:
    return 1.5 if OUTCOME_FAILED_TAG in record.tags else 1.0


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
        self.consolidator = MemoryConsolidator()

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
        now: datetime | None = None,
    ) -> tuple[MemoryRecord, ...]:
        return await asyncio.to_thread(
            self._search_blocking, query, limit=limit, now=now
        )

    def _search_blocking(
        self,
        query: str,
        *,
        limit: int = 10,
        now: datetime | None = None,
    ) -> tuple[MemoryRecord, ...]:
        now = now or datetime.now(UTC)
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM memories").fetchall()

        def _record(row) -> MemoryRecord:
            return MemoryRecord(
                row["memory_id"],
                row["text"],
                row["source_ref"],
                tuple(json.loads(row["tags_json"])),
                row["created_at"],
                row["supersedes"],
            )

        records = tuple(_record(row) for row in rows)
        superseded = {r.supersedes for r in records if r.supersedes}
        records = tuple(r for r in records if r.memory_id not in superseded)
        bm25 = BM25()
        bm25.fit(records)  # ponytail: O(N) refit per search; fine at hundreds, cache if slow
        scored = []
        for record in records:
            strength = _strength(record, now)
            if strength < PRUNE_STRENGTH:
                continue
            score = bm25.score(record, query) * strength * _outcome_boost(record)
            if score > 0:
                scored.append((score, record))
        scored.sort(
            key=lambda item: (item[0], item[1].created_at, item[1].memory_id),
            reverse=True,
        )
        return tuple(record for _, record in scored[:limit])

    async def add(
        self, candidate: MemoryCandidate
    ) -> tuple[ConsolidationAction, str]:
        return await asyncio.to_thread(self._add_blocking, candidate)

    def _add_blocking(
        self, candidate: MemoryCandidate
    ) -> tuple[ConsolidationAction, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memories WHERE normalized_text = ? OR memory_id = ?",
                (normalize(candidate.text), candidate.correction_of),
            ).fetchall()
        matches = tuple(
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
        action = self.consolidator.decide(candidate, matches)
        if action is ConsolidationAction.NOOP:
            existing = next(
                (
                    m
                    for m in matches
                    if normalize(m.text) == normalize(candidate.text)
                    and m.source_ref == candidate.source_ref
                ),
                None,
            )
            assert existing is not None  # decide() 已保证存在 match
            return action, existing.memory_id
        memory_id = str(uuid.uuid4())
        record = MemoryRecord(
            memory_id,
            candidate.text,
            candidate.source_ref,
            candidate.tags,
            datetime.now(UTC).isoformat(),
            candidate.correction_of if action is ConsolidationAction.SUPERSEDE else None,
        )
        self._put_blocking(record)
        return action, memory_id

    async def recent(self, *, limit: int = 5) -> tuple[MemoryRecord, ...]:
        """最近记忆：superseded 过滤，created_at 降序（ISO 串字典序 = 时间序）。"""
        return await asyncio.to_thread(self._recent_blocking, limit)

    def _recent_blocking(self, limit: int) -> tuple[MemoryRecord, ...]:
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
        superseded = {r.supersedes for r in records if r.supersedes}
        records = tuple(r for r in records if r.memory_id not in superseded)
        records = sorted(records, key=lambda r: r.created_at, reverse=True)
        return records[:limit]

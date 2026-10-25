from datetime import datetime

from baremetal_harness.context.builder import DEFAULT_CONTEXT_PRIORITIES
from baremetal_harness.context.types import ContextSource
from baremetal_harness.memory.store import SqliteMemoryStore


class MemoryContextSource:
    def __init__(self, store: SqliteMemoryStore, *, limit: int = 5) -> None:
        self.store = store
        self.limit = limit

    async def build(
        self, query: str, *, now: datetime | None = None
    ) -> ContextSource:
        records = await self.store.search(query, limit=self.limit, now=now)
        text = "\n".join(
            f"[{record.memory_id}] source={record.source_ref}\n{record.text}"
            for record in records
        )
        return ContextSource(
            "memory",
            text,
            DEFAULT_CONTEXT_PRIORITIES["memory"],
        )


class MemoryContextProvider:
    """Adapt MemoryContextSource to the AgentLoop context provider protocol."""

    def __init__(self, store: SqliteMemoryStore, *, limit: int = 5) -> None:
        self.source = MemoryContextSource(store, limit=limit)

    async def build(self, prompt: str) -> tuple[ContextSource, ...]:
        return (await self.source.build(prompt),)

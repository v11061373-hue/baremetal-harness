from datetime import datetime

from baremetal_harness.context.builder import DEFAULT_CONTEXT_PRIORITIES
from baremetal_harness.context.types import ContextSource
from baremetal_harness.memory.store import SqliteMemoryStore


class MemoryContextSource:
    def __init__(
        self, store: SqliteMemoryStore, *, limit: int = 5, max_chars: int = 2000
    ) -> None:
        self.store = store
        self.limit = limit
        self.max_chars = max_chars

    async def build(
        self, query: str, *, now: datetime | None = None
    ) -> ContextSource:
        # 不变——事实级 query top-5，source_id="memory"，required=False（现有测试锁定）
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

    async def build_session(self) -> ContextSource:
        # 新增——会话级最近记忆，source_id="memory:session"，required=True
        records = await self.store.recent(limit=self.limit)
        text = "\n".join(
            f"[{record.memory_id}] source={record.source_ref}\n{record.text}"
            for record in records
        )
        if len(text) > self.max_chars:
            text = text[: self.max_chars] + "\n[... session memory truncated ...]"
        return ContextSource(
            "memory:session", text, DEFAULT_CONTEXT_PRIORITIES["memory"], required=True
        )


class MemoryContextProvider:
    def __init__(
        self, store: SqliteMemoryStore, *, limit: int = 5, max_chars: int = 2000
    ) -> None:
        self.source = MemoryContextSource(store, limit=limit, max_chars=max_chars)

    async def build(self, prompt: str) -> tuple[ContextSource, ...]:
        session = await self.source.build_session()
        facts = await self.source.build(prompt)
        return tuple(source for source in (session, facts) if source.text.strip())

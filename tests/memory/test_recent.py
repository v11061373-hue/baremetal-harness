from baremetal_harness.memory.store import SqliteMemoryStore
from baremetal_harness.memory.types import MemoryRecord


async def test_recent_newest_first(tmp_path) -> None:
    store = SqliteMemoryStore(tmp_path / "state.db", tmp_path / "sources")
    await store.initialize()
    await store.put(
        MemoryRecord("old", "old", "session:1", (), "2026-07-25T00:00:00+00:00")
    )
    await store.put(
        MemoryRecord("new", "new", "session:2", (), "2026-07-26T00:00:00+00:00")
    )

    result = await store.recent(limit=5)

    assert [r.memory_id for r in result] == ["new", "old"]


async def test_recent_skips_superseded(tmp_path) -> None:
    store = SqliteMemoryStore(tmp_path / "state.db", tmp_path / "sources")
    await store.initialize()
    await store.put(
        MemoryRecord("old", "old", "session:1", (), "2026-07-25T00:00:00+00:00")
    )
    await store.put(
        MemoryRecord(
            "new", "new", "session:2", (), "2026-07-26T00:00:00+00:00",
            supersedes="old",
        )
    )

    result = await store.recent(limit=5)

    assert [r.memory_id for r in result] == ["new"]

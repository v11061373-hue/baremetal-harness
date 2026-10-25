from datetime import UTC, datetime
from pathlib import Path

from baremetal_harness.memory.context import MemoryContextSource
from baremetal_harness.memory.store import SqliteMemoryStore
from baremetal_harness.memory.types import MemoryRecord


async def test_search_orders_by_score_then_recency(tmp_path: Path) -> None:
    store = SqliteMemoryStore(tmp_path / "state.db", tmp_path / "sources")
    await store.initialize()
    older = MemoryRecord(
        "older",
        "Python project",
        "session:s1",
        ("python",),
        "2026-07-25T00:00:00+00:00",
    )
    newer = MemoryRecord(
        "newer",
        "Python project",
        "session:s2",
        ("python",),
        "2026-07-26T00:00:00+00:00",
    )
    await store.put(older)
    await store.put(newer)

    assert await store.search(
        "python", now=datetime(2026, 8, 1, tzinfo=UTC)
    ) == (newer, older)


async def test_large_source_is_stored_by_hash(tmp_path: Path) -> None:
    store = SqliteMemoryStore(tmp_path / "state.db", tmp_path / "sources")
    await store.initialize()

    memory = await store.put_with_source(
        memory_id="mem-large",
        text="Large source summary",
        source_content="x" * 5000,
        tags=("large",),
        created_at="2026-07-26T00:00:00+00:00",
    )

    assert memory.source_ref.startswith("file:")
    assert len(tuple((tmp_path / "sources").glob("*.txt"))) == 1


async def test_memory_context_preserves_provenance(tmp_path: Path) -> None:
    store = SqliteMemoryStore(tmp_path / "state.db", tmp_path / "sources")
    await store.initialize()
    await store.put(
        MemoryRecord(
            "mem-1",
            "The project uses Python 3.12",
            "session:s1:message:4",
            ("python",),
            "2026-07-26T00:00:00+00:00",
        )
    )

    source = await MemoryContextSource(store, limit=3).build(
        "python", now=datetime(2026, 8, 1, tzinfo=UTC)
    )

    assert source.source_id == "memory"
    assert "mem-1" in source.text
    assert "session:s1:message:4" in source.text
    assert "Python 3.12" in source.text


from pathlib import Path

from baremetal_harness.memory.store import SqliteMemoryStore
from baremetal_harness.memory.types import MemoryRecord


async def test_memory_round_trip_and_search(tmp_path: Path) -> None:
    store = SqliteMemoryStore(tmp_path / "state.db", tmp_path / "sources")
    await store.initialize()
    memory = MemoryRecord(
        memory_id="mem-1",
        text="The project uses Python 3.12",
        source_ref="session:s1:message:4",
        tags=("project", "python"),
        created_at="2026-07-26T00:00:00+00:00",
    )

    await store.put(memory)

    assert await store.search("python project") == (memory,)


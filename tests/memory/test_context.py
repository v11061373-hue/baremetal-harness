from baremetal_harness.memory.context import MemoryContextProvider
from baremetal_harness.memory.store import SqliteMemoryStore
from baremetal_harness.memory.types import MemoryRecord


async def test_provider_returns_session_and_facts_sources(tmp_path) -> None:
    store = SqliteMemoryStore(tmp_path / "state.db", tmp_path / "sources")
    await store.initialize()
    await store.put(
        MemoryRecord(
            "m1", "The project uses Python 3.12", "session:s1", ("python",),
            "2026-07-26T00:00:00+00:00",
        )
    )

    sources = await MemoryContextProvider(store, limit=5).build("python")

    ids = [s.source_id for s in sources]
    assert "memory:session" in ids
    assert "memory" in ids
    session = next(s for s in sources if s.source_id == "memory:session")
    assert session.required is True
    facts = next(s for s in sources if s.source_id == "memory")
    assert facts.required is False


async def test_provider_abstains_when_store_empty(tmp_path) -> None:
    store = SqliteMemoryStore(tmp_path / "state.db", tmp_path / "sources")
    await store.initialize()

    assert await MemoryContextProvider(store).build("python") == ()


async def test_session_source_is_char_capped(tmp_path) -> None:
    store = SqliteMemoryStore(tmp_path / "state.db", tmp_path / "sources")
    await store.initialize()
    await store.put(
        MemoryRecord("big", "x" * 5000, "session:s1", (), "2026-07-26T00:00:00+00:00")
    )

    provider = MemoryContextProvider(store, limit=5, max_chars=100)
    session = next(
        s for s in await provider.build("") if s.source_id == "memory:session"
    )

    assert "[... session memory truncated ...]" in session.text
    assert len(session.text) <= 100 + 40

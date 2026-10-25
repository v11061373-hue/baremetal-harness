from datetime import UTC, datetime

from baremetal_harness.memory.consolidation import ConsolidationAction, MemoryCandidate
from baremetal_harness.memory.store import SqliteMemoryStore
from baremetal_harness.memory.types import MemoryRecord


def _record(mid, text, created_at, tags=(), supersedes=None):
    return MemoryRecord(
        mid, text, f"inline-sha256:{mid}", tags, created_at, supersedes
    )


async def test_search_drops_superseded(tmp_path) -> None:
    store = SqliteMemoryStore(tmp_path / "m.db", tmp_path / "src")
    await store.initialize()
    await store.put(_record("old", "python memory", "2026-01-01T00:00:00+00:00"))
    await store.put(_record(
        "new", "python memory v2", "2026-01-02T00:00:00+00:00", supersedes="old"
    ))
    ids = [
        r.memory_id
        for r in await store.search("python memory", now=datetime(2026, 2, 1, tzinfo=UTC))
    ]
    assert "old" not in ids
    assert "new" in ids


async def test_search_decay_deprioritizes_old(tmp_path) -> None:
    store = SqliteMemoryStore(tmp_path / "m.db", tmp_path / "src")
    await store.initialize()
    await store.put(_record("old", "python memory", "2026-01-01T00:00:00+00:00"))
    await store.put(_record("new", "python memory", "2026-01-31T00:00:00+00:00"))
    results = await store.search("python memory", now=datetime(2026, 2, 1, tzinfo=UTC))
    assert results[0].memory_id == "new"


async def test_search_failure_fades_faster_than_fact(tmp_path) -> None:
    store = SqliteMemoryStore(tmp_path / "m.db", tmp_path / "src")
    await store.initialize()
    await store.put(_record(
        "fail_old", "python memory", "2026-01-01T00:00:00+00:00",
        tags=("outcome:failed",),
    ))
    await store.put(_record("fact_old", "python memory", "2026-01-01T00:00:00+00:00"))
    results = await store.search("python memory", now=datetime(2026, 2, 1, tzinfo=UTC))
    assert results[0].memory_id == "fact_old"


async def test_search_boosts_fresh_outcome_failed(tmp_path) -> None:
    store = SqliteMemoryStore(tmp_path / "m.db", tmp_path / "src")
    await store.initialize()
    await store.put(_record("ok", "python memory", "2026-01-31T00:00:00+00:00"))
    await store.put(_record(
        "fail", "python memory", "2026-01-31T00:00:00+00:00",
        tags=("outcome:failed",),
    ))
    results = await store.search("python memory", now=datetime(2026, 2, 1, tzinfo=UTC))
    assert results[0].memory_id == "fail"


async def test_search_prunes_stale(tmp_path) -> None:
    store = SqliteMemoryStore(tmp_path / "m.db", tmp_path / "src")
    await store.initialize()
    await store.put(_record("ancient", "python memory", "2020-01-01T00:00:00+00:00"))
    results = await store.search("python memory", now=datetime(2026, 2, 1, tzinfo=UTC))
    assert [r.memory_id for r in results] == []


async def test_search_naive_created_at_does_not_crash(tmp_path) -> None:
    store = SqliteMemoryStore(tmp_path / "m.db", tmp_path / "src")
    await store.initialize()
    await store.put(_record("naive", "python memory", "2026-01-01T00:00:00"))
    results = await store.search("python memory", now=datetime(2026, 2, 1, tzinfo=UTC))
    assert [r.memory_id for r in results] == ["naive"]


async def test_add_dedups_exact_duplicate(tmp_path) -> None:
    store = SqliteMemoryStore(tmp_path / "m.db", tmp_path / "src")
    await store.initialize()
    cand = MemoryCandidate("python memory", "inline-sha256:x", ())
    action1, id1 = await store.add(cand)
    action2, id2 = await store.add(cand)
    assert action1 is ConsolidationAction.CREATE
    assert action2 is ConsolidationAction.NOOP
    assert id1 == id2


async def test_add_supersedes_on_correction(tmp_path) -> None:
    store = SqliteMemoryStore(tmp_path / "m.db", tmp_path / "src")
    await store.initialize()
    _, first_id = await store.add(MemoryCandidate("python is fast", "inline-sha256:x", ()))
    action, new_id = await store.add(
        MemoryCandidate(
            "python is fast but GIL-bound", "inline-sha256:y", (),
            correction_of=first_id,
        )
    )
    assert action is ConsolidationAction.SUPERSEDE
    ids = [r.memory_id for r in await store.search("python")]
    assert new_id in ids
    assert first_id not in ids

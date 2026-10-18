import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from baremetal_harness.agent.loop import RunStarted
from baremetal_harness.core.events import EventEnvelope
from baremetal_harness.sessions.events import JsonlEventStore
from baremetal_harness.sessions.serialization import PersistenceError


def envelope(event_id: str, sequence: int, run_id: str = "run-1") -> EventEnvelope:
    return EventEnvelope(
        event_id,
        run_id,
        "session-1",
        sequence,
        datetime(2026, 7, 26, tzinfo=UTC),
        RunStarted("hello"),
        None,
    )


async def test_appends_stay_linear_as_the_log_grows(tmp_path: Path) -> None:
    store = JsonlEventStore(tmp_path / "events.jsonl")
    for index in range(1, 401):
        await store.append(envelope(f"warmup-{index}", index))

    start = time.perf_counter()
    for index in range(401, 501):
        await store.append(envelope(f"tail-{index}", index))
    tail = time.perf_counter() - start

    fresh = JsonlEventStore(tmp_path / "fresh.jsonl")
    start = time.perf_counter()
    for index in range(1, 101):
        await fresh.append(envelope(f"head-{index}", index))
    head = time.perf_counter() - start

    # With a full re-parse per append this ratio grows with log size; the
    # cached index keeps appending to a long log close to appending to a new one.
    assert tail < head * 10 + 0.05


async def test_index_notices_writes_from_another_store_instance(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.jsonl"
    first = JsonlEventStore(path)
    second = JsonlEventStore(path)

    await first.append(envelope("event-1", 1))
    await second.append(envelope("event-2", 2))
    # first must not believe sequence 2 is still free.
    with pytest.raises(PersistenceError, match="sequence"):
        await first.append(envelope("event-3", 2))

    await first.append(envelope("event-3", 3))
    assert len(await first.load()) == 3


async def test_conflicting_duplicate_is_still_rejected(tmp_path: Path) -> None:
    store = JsonlEventStore(tmp_path / "events.jsonl")
    await store.append(envelope("event-1", 1))

    with pytest.raises(PersistenceError, match="duplicate"):
        await store.append(
            EventEnvelope(
                "event-1",
                "run-1",
                "session-1",
                1,
                datetime(2026, 7, 26, tzinfo=UTC),
                RunStarted("different payload"),
                None,
            )
        )


async def test_identical_duplicate_is_still_ignored(tmp_path: Path) -> None:
    store = JsonlEventStore(tmp_path / "events.jsonl")
    first = envelope("event-1", 1)

    await store.append(first)
    await store.append(first)

    assert await store.load() == (first,)


async def test_sequences_stay_scoped_per_run(tmp_path: Path) -> None:
    store = JsonlEventStore(tmp_path / "events.jsonl")

    await store.append(envelope("a-1", 1, run_id="run-a"))
    await store.append(envelope("b-1", 1, run_id="run-b"))
    await store.append(envelope("a-2", 2, run_id="run-a"))

    assert len(await store.load()) == 3

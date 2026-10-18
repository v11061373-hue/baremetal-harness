from datetime import UTC, datetime
from pathlib import Path

import pytest

from baremetal_harness.agent.loop import RunStarted
from baremetal_harness.core.events import EventEnvelope
from baremetal_harness.sessions.events import JsonlEventStore
from baremetal_harness.sessions.serialization import PersistenceError


def envelope(event_id: str, sequence: int) -> EventEnvelope:
    return EventEnvelope(
        event_id,
        "run-1",
        "session-1",
        sequence,
        datetime(2026, 7, 26, tzinfo=UTC),
        RunStarted("hello"),
        None,
    )


async def test_event_store_is_ordered_and_idempotent(tmp_path: Path) -> None:
    store = JsonlEventStore(tmp_path / "events.jsonl")
    first = envelope("event-1", 1)

    await store.append(first)
    await store.append(first)

    assert await store.load() == (first,)


async def test_event_store_rejects_sequence_gap(tmp_path: Path) -> None:
    store = JsonlEventStore(tmp_path / "events.jsonl")

    with pytest.raises(PersistenceError, match="sequence"):
        await store.append(envelope("event-2", 2))


async def test_event_store_sequence_is_scoped_to_run(tmp_path: Path) -> None:
    store = JsonlEventStore(tmp_path / "events.jsonl")
    first = envelope("event-1", 1)
    second_run = EventEnvelope(
        "event-2",
        "run-2",
        "session-2",
        1,
        datetime(2026, 7, 26, tzinfo=UTC),
        RunStarted("second"),
        None,
    )

    await store.append(first)
    await store.append(second_run)

    assert await store.load() == (first, second_run)


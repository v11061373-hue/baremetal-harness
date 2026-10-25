from datetime import UTC, datetime
from pathlib import Path

from baremetal_harness.agent.loop import BudgetExceeded, PermissionEvaluated
from baremetal_harness.core.events import EventEnvelope
from baremetal_harness.sessions.events import JsonlEventStore


async def test_permission_evaluated_roundtrips(tmp_path: Path) -> None:
    store = JsonlEventStore(tmp_path / "events.jsonl")
    envelope = EventEnvelope(
        "event-1", "run-1", "session-1", 1,
        datetime(2026, 7, 26, tzinfo=UTC),
        PermissionEvaluated("run_command", "deny", "destructive", "abc123"),
        None,
    )
    await store.append(envelope)
    (loaded,) = await store.load()
    assert loaded.payload == PermissionEvaluated(
        "run_command", "deny", "destructive", "abc123"
    )


async def test_budget_exceeded_roundtrips(tmp_path: Path) -> None:
    store = JsonlEventStore(tmp_path / "events.jsonl")
    envelope = EventEnvelope(
        "event-1", "run-1", "session-1", 1,
        datetime(2026, 7, 26, tzinfo=UTC),
        BudgetExceeded("turns"),
        None,
    )
    await store.append(envelope)
    (loaded,) = await store.load()
    assert loaded.payload == BudgetExceeded("turns")

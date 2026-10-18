from datetime import UTC, datetime
from pathlib import Path

from baremetal_harness.agent.loop import AgentLoop
from baremetal_harness.core.messages import ResponseCompleted, TextDelta
from baremetal_harness.model.fake import FakeModel
from baremetal_harness.sessions.checkpoints import FileCheckpointStore
from baremetal_harness.sessions.database import SessionRepository
from baremetal_harness.sessions.events import JsonlEventStore


async def test_agent_persists_events_and_final_checkpoint(tmp_path: Path) -> None:
    repository = SessionRepository(tmp_path / "state.db")
    await repository.initialize()
    checkpoints = FileCheckpointStore(tmp_path / "checkpoints", repository)
    events = JsonlEventStore(tmp_path / "events.jsonl")
    loop = AgentLoop(
        FakeModel((TextDelta("done"), ResponseCompleted("stop"))),
        "fake",
        session_repository=repository,
        checkpoint_store=checkpoints,
        event_store=events,
        clock=lambda: datetime(2026, 7, 26, tzinfo=UTC),
    )

    result = await loop.run("persist this")

    stored = await checkpoints.latest_for_run(result.run_id)
    assert stored is not None
    assert stored.status == "completed"
    assert stored.messages == result.messages
    assert await events.load() == result.events

from datetime import UTC, datetime
from pathlib import Path

from baremetal_harness.sessions.checkpoints import FileCheckpointStore
from baremetal_harness.sessions.database import SessionRepository
from baremetal_harness.sessions.types import Checkpoint, RunRecord, SessionRecord


async def test_checkpoint_round_trip(tmp_path: Path) -> None:
    now = datetime(2026, 7, 26, tzinfo=UTC)
    repository = SessionRepository(tmp_path / "state.db")
    await repository.initialize()
    await repository.create_session(
        SessionRecord(
            session_id="session-1",
            created_at=now,
            updated_at=now,
        )
    )
    await repository.create_run(
        RunRecord(
            run_id="run-1",
            session_id="session-1",
            status="running",
            started_at=now,
            updated_at=now,
        )
    )
    store = FileCheckpointStore(tmp_path / "checkpoints", repository)
    checkpoint = Checkpoint(
        checkpoint_id="cp-1",
        run_id="run-1",
        session_id="session-1",
        sequence=4,
        status="recording_results",
        messages=(),
        completed_tool_executions=("tool-1",),
    )

    path = await store.save(checkpoint)

    assert path.exists()
    assert await store.load("cp-1") == checkpoint
    assert await store.latest_for_run("run-1") == checkpoint


from datetime import UTC, datetime
from pathlib import Path

from baremetal_harness.sessions.database import SessionRepository
from baremetal_harness.sessions.types import RunRecord, SessionRecord


async def test_repository_persists_run_across_instances(tmp_path: Path) -> None:
    now = datetime(2026, 7, 26, tzinfo=UTC)
    path = tmp_path / "state.db"
    repository = SessionRepository(path)
    await repository.initialize()
    await repository.create_session(SessionRecord("session-1", now, now))
    await repository.create_run(
        RunRecord("run-1", "session-1", "running", now, now)
    )

    reopened = SessionRepository(path)

    assert await reopened.get_run("run-1") == RunRecord(
        "run-1",
        "session-1",
        "running",
        now,
        now,
    )


async def test_corrupt_checkpoint_is_rejected(tmp_path: Path) -> None:
    from baremetal_harness.sessions.checkpoints import (
        CheckpointCorrupted,
        FileCheckpointStore,
    )
    from baremetal_harness.sessions.types import Checkpoint

    now = datetime(2026, 7, 26, tzinfo=UTC)
    repository = SessionRepository(tmp_path / "state.db")
    await repository.initialize()
    await repository.create_session(SessionRecord("session-1", now, now))
    await repository.create_run(
        RunRecord("run-1", "session-1", "running", now, now)
    )
    store = FileCheckpointStore(tmp_path / "checkpoints", repository)
    path = await store.save(
        Checkpoint("cp-1", "run-1", "session-1", 1, "running", (), ())
    )
    path.write_text("{}")

    import pytest

    with pytest.raises(CheckpointCorrupted):
        await store.load("cp-1")

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from baremetal_harness.sessions.database import SessionRepository
from baremetal_harness.sessions.serialization import (
    PersistenceError,
    decode_checkpoint,
    encode_checkpoint,
)
from baremetal_harness.sessions.types import Checkpoint


class CheckpointNotFound(PersistenceError):
    pass


class CheckpointCorrupted(PersistenceError):
    pass


class FileCheckpointStore:
    def __init__(
        self,
        checkpoint_directory: Path,
        repository: SessionRepository,
    ) -> None:
        self.checkpoint_directory = checkpoint_directory
        self.repository = repository

    async def save(self, checkpoint: Checkpoint) -> Path:
        self.checkpoint_directory.mkdir(parents=True, exist_ok=True)
        data = json.dumps(
            encode_checkpoint(checkpoint),
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        digest = hashlib.sha256(data).hexdigest()
        path = self.checkpoint_directory / f"{checkpoint.checkpoint_id}.json"
        temporary = path.with_suffix(".json.tmp")
        with temporary.open("wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
        await self.repository.record_checkpoint(
            checkpoint_id=checkpoint.checkpoint_id,
            run_id=checkpoint.run_id,
            sequence=checkpoint.sequence,
            path=path,
            sha256=digest,
            created_at=datetime.now(UTC),
            run_status=checkpoint.status,
        )
        return path

    async def load(self, checkpoint_id: str) -> Checkpoint:
        index = await self.repository.checkpoint_index(checkpoint_id)
        if index is None:
            raise CheckpointNotFound(f"checkpoint not found: {checkpoint_id}")
        try:
            data = index.path.read_bytes()
        except FileNotFoundError as exc:
            raise CheckpointNotFound(
                f"checkpoint not found: {checkpoint_id}"
            ) from exc
        if hashlib.sha256(data).hexdigest() != index.sha256:
            raise CheckpointCorrupted("checkpoint checksum mismatch")
        try:
            payload = json.loads(data)
            if not isinstance(payload, dict):
                raise TypeError
            return decode_checkpoint(payload)
        except (json.JSONDecodeError, TypeError, PersistenceError) as exc:
            raise CheckpointCorrupted("checkpoint payload is invalid") from exc

    async def latest_for_run(self, run_id: str) -> Checkpoint | None:
        index = await self.repository.latest_checkpoint_index(run_id)
        if index is None:
            return None
        return await self.load(index.checkpoint_id)

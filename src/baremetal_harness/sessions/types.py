from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from baremetal_harness.context.types import AgentContext
from baremetal_harness.core.messages import Message


@dataclass(frozen=True, slots=True)
class SessionRecord:
    session_id: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    session_id: str
    status: str
    started_at: datetime
    updated_at: datetime
    latest_checkpoint_id: str | None = None


@dataclass(frozen=True, slots=True)
class CheckpointIndex:
    checkpoint_id: str
    run_id: str
    sequence: int
    path: Path
    sha256: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Checkpoint:
    checkpoint_id: str
    run_id: str
    session_id: str
    sequence: int
    status: str
    messages: tuple[Message, ...]
    completed_tool_executions: tuple[str, ...]
    context_snapshot: AgentContext | None = None


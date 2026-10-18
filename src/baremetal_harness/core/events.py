from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_id: str
    run_id: str
    session_id: str
    sequence: int
    timestamp: datetime
    payload: object
    parent_event_id: str | None = None

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        session_id: str,
        sequence: int,
        payload: object,
        parent_event_id: str | None = None,
    ) -> "EventEnvelope":
        return cls(
            event_id=str(uuid4()),
            run_id=run_id,
            session_id=session_id,
            sequence=sequence,
            timestamp=datetime.now(UTC),
            payload=payload,
            parent_event_id=parent_event_id,
        )

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Protocol

from baremetal_harness.core.events import EventEnvelope
from baremetal_harness.observability.redaction import Redactor


class TraceSink(Protocol):
    async def emit(self, event: EventEnvelope) -> None: ...


class CompositeTraceSink:
    def __init__(self, sinks: tuple[TraceSink, ...]) -> None:
        self.sinks = sinks

    async def emit(self, event: EventEnvelope) -> None:
        for sink in self.sinks:
            await sink.emit(event)


class JsonlTraceSink:
    def __init__(self, directory: Path, *, secrets: tuple[str, ...] = ()) -> None:
        self.directory = directory
        self.redactor = Redactor(secrets)

    async def emit(self, event: EventEnvelope) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{event.timestamp.date().isoformat()}.jsonl"
        raw_payload = (
            asdict(event.payload)
            if is_dataclass(event.payload)
            else event.payload
        )
        record = {
            "event_id": event.event_id,
            "run_id": event.run_id,
            "session_id": event.session_id,
            "sequence": event.sequence,
            "timestamp": event.timestamp.isoformat(),
            "payload_type": event.payload.__class__.__name__,
            "payload": self.redactor.redact(raw_payload),
            "parent_event_id": event.parent_event_id,
        }
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, separators=(",", ":"), sort_keys=True))
            file.write("\n")
            file.flush()

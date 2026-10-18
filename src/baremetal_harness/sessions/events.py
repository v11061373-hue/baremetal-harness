import json
from pathlib import Path

from baremetal_harness.core.events import EventEnvelope
from baremetal_harness.sessions.serialization import (
    PersistenceError,
    decode_event,
    encode_event,
)


class JsonlEventStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        # Appending once per streamed delta must not re-parse the whole log,
        # so validation state is cached and rebuilt only when the file changed
        # underneath us (another store instance or process wrote to it).
        self._indexed_size = -1
        self._event_ids: set[str] = set()
        self._last_sequence: dict[str, int] = {}

    def _file_size(self) -> int:
        try:
            return self.path.stat().st_size
        except FileNotFoundError:
            return 0

    async def _sync_index(self) -> None:
        size = self._file_size()
        if size == self._indexed_size:
            return
        event_ids: set[str] = set()
        last_sequence: dict[str, int] = {}
        for event in await self.load():
            event_ids.add(event.event_id)
            last_sequence[event.run_id] = event.sequence
        self._event_ids = event_ids
        self._last_sequence = last_sequence
        self._indexed_size = size

    async def append(self, envelope: EventEnvelope) -> None:
        await self._sync_index()
        if envelope.event_id in self._event_ids:
            previous = next(
                (
                    event
                    for event in await self.load()
                    if event.event_id == envelope.event_id
                ),
                None,
            )
            if previous == envelope:
                return
            raise PersistenceError("conflicting duplicate event id")
        expected_sequence = self._last_sequence.get(envelope.run_id, 0) + 1
        if envelope.sequence != expected_sequence:
            raise PersistenceError("event sequence is not contiguous")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(
                json.dumps(
                    encode_event(envelope),
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            file.write("\n")
            file.flush()
        self._event_ids.add(envelope.event_id)
        self._last_sequence[envelope.run_id] = envelope.sequence
        self._indexed_size = self._file_size()

    async def load(self) -> tuple[EventEnvelope, ...]:
        if not self.path.exists():
            return ()
        events = []
        try:
            for line in self.path.read_text().splitlines():
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise TypeError
                events.append(decode_event(payload))
        except (json.JSONDecodeError, TypeError) as exc:
            raise PersistenceError("invalid event log") from exc
        return tuple(events)

from collections.abc import AsyncIterator, Iterable

from baremetal_harness.core.messages import ModelEvent, ModelRequest


class FakeModel:
    def __init__(self, events: Iterable[ModelEvent]) -> None:
        self._events = tuple(events)
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        self.requests.append(request)
        for event in self._events:
            yield event

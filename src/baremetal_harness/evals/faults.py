from collections.abc import AsyncIterator

from baremetal_harness.core.messages import ModelEvent, ModelRequest


class DisconnectingModel:
    def __init__(self, provider, *, after_event: int) -> None:
        self.provider = provider
        self.after_event = after_event

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        count = 0
        async for event in self.provider.stream(request):
            if count >= self.after_event:
                raise ConnectionError("injected model disconnect")
            count += 1
            yield event
        if count >= self.after_event:
            raise ConnectionError("injected model disconnect")

from collections.abc import AsyncIterator, Iterable

from baremetal_harness.core.messages import ModelEvent, ModelRequest


class ScriptedModel:
    def __init__(self, turns: Iterable[Iterable[ModelEvent]]) -> None:
        self._turns = [tuple(turn) for turn in turns]
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        self.requests.append(request)
        turn_index = len(self.requests) - 1
        if turn_index >= len(self._turns):
            raise AssertionError(f"unexpected model turn: {turn_index + 1}")
        for event in self._turns[turn_index]:
            yield event

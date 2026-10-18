import json
from dataclasses import dataclass

from baremetal_harness.core.errors import ToolArgumentsInvalid
from baremetal_harness.core.messages import ToolCall, ToolCallDelta


@dataclass(slots=True)
class _ToolCallBuffer:
    call_id: str | None = None
    name: str | None = None
    arguments: str = ""


class ToolCallAssembler:
    def __init__(self) -> None:
        self._buffers: dict[int, _ToolCallBuffer] = {}

    def feed(self, delta: ToolCallDelta) -> None:
        buffer = self._buffers.setdefault(delta.index, _ToolCallBuffer())
        if delta.call_id is not None:
            if buffer.call_id not in {None, delta.call_id}:
                raise ToolArgumentsInvalid("conflicting tool call id")
            buffer.call_id = delta.call_id
        if delta.name is not None:
            if buffer.name not in {None, delta.name}:
                raise ToolArgumentsInvalid("conflicting tool call name")
            buffer.name = delta.name
        buffer.arguments += delta.arguments_fragment

    def complete(self) -> tuple[ToolCall, ...]:
        calls: list[ToolCall] = []
        for index in sorted(self._buffers):
            buffer = self._buffers[index]
            if buffer.call_id is None or buffer.name is None:
                raise ToolArgumentsInvalid("incomplete tool call identity")
            try:
                arguments = json.loads(buffer.arguments or "{}")
            except json.JSONDecodeError as exc:
                raise ToolArgumentsInvalid("malformed tool arguments") from exc
            if not isinstance(arguments, dict):
                raise ToolArgumentsInvalid("tool arguments must be an object")
            calls.append(ToolCall(buffer.call_id, buffer.name, arguments))
        return tuple(calls)

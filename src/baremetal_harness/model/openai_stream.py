from baremetal_harness.core.errors import ModelProtocolError
from baremetal_harness.core.messages import (
    ModelEvent,
    ResponseCompleted,
    TextDelta,
    ToolCallDelta,
    Usage,
)


def decode_openai_chunk(payload: dict[str, object]) -> tuple[ModelEvent, ...]:
    try:
        choices = payload["choices"]
        if not isinstance(choices, list):
            raise TypeError
        choice = choices[0]
        if not isinstance(choice, dict):
            raise TypeError
        delta = choice.get("delta") or {}
        if not isinstance(delta, dict):
            raise TypeError
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelProtocolError("invalid streaming chunk") from exc

    events: list[ModelEvent] = []
    content = delta.get("content")
    if isinstance(content, str) and content:
        events.append(TextDelta(content))

    raw_tool_calls = delta.get("tool_calls") or []
    if not isinstance(raw_tool_calls, list):
        raise ModelProtocolError("invalid streaming tool calls")
    for raw in raw_tool_calls:
        if not isinstance(raw, dict):
            raise ModelProtocolError("invalid streaming tool call")
        function = raw.get("function") or {}
        if not isinstance(function, dict) or not isinstance(raw.get("index"), int):
            raise ModelProtocolError("invalid streaming tool call")
        events.append(
            ToolCallDelta(
                index=raw["index"],
                call_id=raw.get("id") if isinstance(raw.get("id"), str) else None,
                name=(
                    function.get("name")
                    if isinstance(function.get("name"), str)
                    else None
                ),
                arguments_fragment=(
                    function.get("arguments")
                    if isinstance(function.get("arguments"), str)
                    else ""
                ),
            )
        )

    finish_reason = choice.get("finish_reason")
    if isinstance(finish_reason, str) and finish_reason:
        raw_usage = payload.get("usage")
        usage = None
        if raw_usage is not None:
            try:
                if not isinstance(raw_usage, dict):
                    raise TypeError
                usage = Usage(
                    int(raw_usage["prompt_tokens"]),
                    int(raw_usage["completion_tokens"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ModelProtocolError("invalid streaming usage") from exc
        events.append(ResponseCompleted(finish_reason, usage))
    return tuple(events)

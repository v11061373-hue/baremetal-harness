import json

from baremetal_harness.core.messages import (
    Message,
    ModelRequest,
    TextContent,
    ToolCall,
    ToolResultContent,
)


def encode_message(message: Message) -> dict[str, object]:
    tool_calls = [item for item in message.content if isinstance(item, ToolCall)]
    tool_results = [
        item for item in message.content if isinstance(item, ToolResultContent)
    ]
    if tool_calls:
        return {
            "role": message.role,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            call.arguments,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                    },
                }
                for call in tool_calls
            ],
        }
    if tool_results:
        if len(tool_results) != 1:
            raise ValueError("tool messages contain exactly one result")
        result = tool_results[0]
        return {
            "role": "tool",
            "tool_call_id": result.tool_call_id,
            "content": result.output,
        }
    texts = [item.text for item in message.content if isinstance(item, TextContent)]
    return {"role": message.role, "content": "".join(texts)}


def encode_request(request: ModelRequest, *, stream: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": request.model,
        "messages": [encode_message(message) for message in request.messages],
        "temperature": request.temperature,
        "stream": stream,
    }
    if request.tools:
        payload["tools"] = list(request.tools)
    return payload

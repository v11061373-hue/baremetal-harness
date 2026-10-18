import json

import httpx
import pytest

from baremetal_harness.core.errors import ModelProtocolError
from baremetal_harness.core.messages import (
    ModelRequest,
    ResponseCompleted,
    TextDelta,
    ToolCallDelta,
    Usage,
)
from baremetal_harness.model.openai_compat import OpenAICompatibleClient
from baremetal_harness.model.openai_stream import decode_openai_chunk


def test_decode_text_and_tool_deltas() -> None:
    payload = {
        "choices": [
            {
                "delta": {
                    "content": "hi",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call-1",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path"',
                            },
                        }
                    ],
                },
                "finish_reason": None,
            }
        ]
    }

    assert decode_openai_chunk(payload) == (
        TextDelta("hi"),
        ToolCallDelta(0, "call-1", "read_file", '{"path"'),
    )


def test_decode_completion_usage() -> None:
    payload = {
        "choices": [{"delta": {}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    }

    assert decode_openai_chunk(payload) == (
        ResponseCompleted("stop", Usage(3, 2)),
    )


async def test_client_streams_sse_events() -> None:
    chunks = [
        {
            "choices": [
                {"delta": {"content": "hello"}, "finish_reason": None}
            ]
        },
        {
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        },
    ]
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
    body += "data: [DONE]\n\n"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=body)
    )
    client = OpenAICompatibleClient(
        "https://model.invalid/v1",
        "test-key",
        transport=transport,
    )

    events = [event async for event in client.stream(ModelRequest("demo", ()))]
    await client.aclose()

    assert events == [
        TextDelta("hello"),
        ResponseCompleted("stop", Usage(2, 1)),
    ]


async def test_client_rejects_stream_without_completion() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            "data: [DONE]\n\n",
        )
    )
    client = OpenAICompatibleClient(
        "https://model.invalid/v1",
        "test-key",
        transport=transport,
    )

    with pytest.raises(ModelProtocolError, match="without completion"):
        _ = [event async for event in client.stream(ModelRequest("demo", ()))]
    await client.aclose()

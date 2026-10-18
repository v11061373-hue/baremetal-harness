import json

import httpx
import pytest

from baremetal_harness.core.errors import (
    AuthenticationError,
    ModelUnavailableError,
    RateLimitError,
)
from baremetal_harness.core.messages import (
    Message,
    ModelRequest,
    ResponseCompleted,
    TextContent,
    TextDelta,
)
from baremetal_harness.model.openai_compat import OpenAICompatibleClient


async def test_client_encodes_messages_and_auth_header() -> None:
    auth_scheme = "Bearer"
    test_key = "test-key"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://model.invalid/v1/chat/completions"
        assert request.headers["authorization"] == f"{auth_scheme} {test_key}"
        payload = json.loads(request.content)
        assert payload["messages"] == [{"role": "user", "content": "hello"}]
        assert payload["stream"] is True
        return httpx.Response(
            200,
            text=(
                'data: {"choices":[{"delta":{"content":"world"},'
                '"finish_reason":null}]}\n\n'
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    client = OpenAICompatibleClient(
        base_url="https://model.invalid/v1",
        api_key=test_key,
        transport=httpx.MockTransport(handler),
    )
    request = ModelRequest("demo", (Message("user", (TextContent("hello"),)),))

    events = [event async for event in client.stream(request)]
    await client.aclose()

    assert events == [TextDelta("world"), ResponseCompleted("stop")]


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, AuthenticationError),
        (403, AuthenticationError),
        (429, RateLimitError),
        (500, ModelUnavailableError),
    ],
)
async def test_client_maps_http_errors(
    status: int,
    error_type: type[Exception],
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, json={"error": {"message": "safe"}})
    )
    # Error mapping is the subject here, so retries are switched off.
    client = OpenAICompatibleClient(
        "https://model.invalid/v1",
        "test-key",
        transport=transport,
        max_attempts=1,
    )

    with pytest.raises(error_type) as raised:
        _ = [event async for event in client.stream(ModelRequest("demo", ()))]
    await client.aclose()

    assert "test-key" not in repr(raised.value)


async def test_timeout_maps_to_unavailable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    # Timeouts are retryable, so this maps one attempt rather than waiting.
    client = OpenAICompatibleClient(
        "https://model.invalid/v1",
        "test-key",
        transport=httpx.MockTransport(handler),
        max_attempts=1,
    )

    with pytest.raises(ModelUnavailableError, match="timed out"):
        _ = [event async for event in client.stream(ModelRequest("demo", ()))]
    await client.aclose()

import httpx
import pytest

from baremetal_harness.core.errors import ModelUnavailableError, RateLimitError
from baremetal_harness.core.messages import (
    ModelRequest,
    ResponseCompleted,
    TextDelta,
)
from baremetal_harness.model.openai_compat import OpenAICompatibleClient

STREAM = (
    'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":null}]}\n\n'
    'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
    "data: [DONE]\n\n"
)


class Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _client(handler, sleeps, **kwargs) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        "https://model.invalid/v1",
        "test-key",
        transport=httpx.MockTransport(handler),
        sleep=sleeps,
        **kwargs,
    )


async def _drain(client) -> list:
    return [event async for event in client.stream(ModelRequest("demo", ()))]


async def test_rate_limit_is_retried_until_it_succeeds() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(429, json={})
        return httpx.Response(200, text=STREAM)

    sleeps = Sleeps()
    client = _client(handler, sleeps)
    events = await _drain(client)
    await client.aclose()

    assert events == [TextDelta("ok"), ResponseCompleted("stop")]
    assert attempts == 3
    assert len(sleeps.delays) == 2


async def test_server_errors_are_retried_too() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return (
            httpx.Response(503, json={})
            if attempts == 1
            else httpx.Response(200, text=STREAM)
        )

    client = _client(handler, Sleeps())
    events = await _drain(client)
    await client.aclose()

    assert events == [TextDelta("ok"), ResponseCompleted("stop")]


async def test_attempts_are_bounded() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, json={})

    sleeps = Sleeps()
    client = _client(handler, sleeps, max_attempts=3)

    with pytest.raises(RateLimitError):
        await _drain(client)
    await client.aclose()

    assert attempts == 3
    assert len(sleeps.delays) == 2


async def test_backoff_grows_and_is_jittered() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={})

    sleeps = Sleeps()
    client = _client(handler, sleeps, max_attempts=4, backoff_base_seconds=1.0)

    with pytest.raises(ModelUnavailableError):
        await _drain(client)
    await client.aclose()

    # Each window is half-open jitter over [w/2, w) with w doubling.
    assert 0.5 <= sleeps.delays[0] <= 1.0
    assert 1.0 <= sleeps.delays[1] <= 2.0
    assert 2.0 <= sleeps.delays[2] <= 4.0


async def test_retry_after_header_is_honoured() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={}, headers={"retry-after": "7"})

    sleeps = Sleeps()
    client = _client(handler, sleeps, max_attempts=2)

    with pytest.raises(RateLimitError):
        await _drain(client)
    await client.aclose()

    assert sleeps.delays == [7.0]


async def test_retry_after_is_capped() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={}, headers={"retry-after": "9999"})

    sleeps = Sleeps()
    client = _client(handler, sleeps, max_attempts=2, backoff_cap_seconds=20.0)

    with pytest.raises(RateLimitError):
        await _drain(client)
    await client.aclose()

    assert sleeps.delays == [20.0]


async def test_a_stream_that_already_emitted_is_not_retried() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        # Emits one delta, then ends without a completion event.
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"partial"},'
            '"finish_reason":null}]}\n\n',
        )

    from baremetal_harness.core.errors import ModelProtocolError

    client = _client(handler, Sleeps())

    with pytest.raises(ModelProtocolError):
        await _drain(client)
    await client.aclose()

    # Retrying here would duplicate the text the caller already received.
    assert attempts == 1


async def test_authentication_failure_is_not_retried() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, json={})

    from baremetal_harness.core.errors import AuthenticationError

    client = _client(handler, Sleeps())

    with pytest.raises(AuthenticationError):
        await _drain(client)
    await client.aclose()

    assert attempts == 1

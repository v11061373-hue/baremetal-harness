import asyncio
import json
import random
from collections.abc import AsyncIterator

import httpx

from baremetal_harness.core.errors import (
    AuthenticationError,
    ModelProtocolError,
    ModelUnavailableError,
    RateLimitError,
)
from baremetal_harness.core.messages import (
    ModelEvent,
    ModelRequest,
    ResponseCompleted,
)
from baremetal_harness.model.encoding import encode_request
from baremetal_harness.model.openai_stream import decode_openai_chunk
from baremetal_harness.model.sse import SSEDecoder


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        max_attempts: int = 4,
        backoff_base_seconds: float = 0.5,
        backoff_cap_seconds: float = 20.0,
        sleep=asyncio.sleep,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.max_attempts = max_attempts
        self.backoff_base_seconds = backoff_base_seconds
        self.backoff_cap_seconds = backoff_cap_seconds
        self._sleep = sleep

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        """Stream one completion, retrying only before the first event.

        Rate limits and 5xx are routine, but a stream that has already yielded
        text cannot be restarted without duplicating it, so a retry is only
        safe while nothing has been emitted. Once output has started, the
        error propagates.
        """
        for attempt in range(1, self.max_attempts + 1):
            started = False
            try:
                async for event in self._stream_once(request):
                    started = True
                    yield event
                return
            except (RateLimitError, ModelUnavailableError) as error:
                if started or attempt == self.max_attempts:
                    raise
                await self._sleep(self._delay(attempt, error))

    def _delay(self, attempt: int, error: Exception) -> float:
        retry_after = getattr(error, "retry_after", None)
        if retry_after is not None:
            return min(float(retry_after), self.backoff_cap_seconds)
        # Exponential backoff with jitter, so concurrent agents do not retry
        # in lockstep and re-create the burst that caused the rate limit.
        window = min(
            self.backoff_base_seconds * (2 ** (attempt - 1)),
            self.backoff_cap_seconds,
        )
        return random.uniform(window / 2, window)

    async def _stream_once(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        try:
            async with self._client.stream(
                "POST",
                "chat/completions",
                json=encode_request(request, stream=True),
            ) as response:
                self._raise_for_status(response)
                decoder = SSEDecoder()
                completed = False
                async for chunk in response.aiter_bytes():
                    for data in decoder.feed(chunk):
                        if data == "[DONE]":
                            if not completed:
                                raise ModelProtocolError(
                                    "model stream ended without completion"
                                )
                            return
                        try:
                            payload = json.loads(data)
                        except json.JSONDecodeError as exc:
                            raise ModelProtocolError(
                                "invalid streaming json"
                            ) from exc
                        if not isinstance(payload, dict):
                            raise ModelProtocolError("invalid streaming json")
                        for event in decode_openai_chunk(payload):
                            if isinstance(event, ResponseCompleted):
                                completed = True
                            yield event
                if not completed:
                    raise ModelProtocolError("model stream ended without completion")
        except httpx.TimeoutException as exc:
            raise ModelUnavailableError("model request timed out") from exc

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code in {401, 403}:
            raise AuthenticationError("model authentication failed")
        if response.status_code == 429:
            error = RateLimitError("model rate limit exceeded")
            error.retry_after = _retry_after(response)
            raise error
        if response.status_code >= 500:
            error = ModelUnavailableError("model service unavailable")
            error.retry_after = _retry_after(response)
            raise error
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ModelProtocolError("model request failed") from exc

    async def aclose(self) -> None:
        await self._client.aclose()


def _retry_after(response: httpx.Response) -> float | None:
    """Honour a server-supplied Retry-After delay when it is a plain number."""
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None

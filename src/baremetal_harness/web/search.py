from dataclasses import dataclass, field
from typing import Protocol

import httpx


class SearchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchProvider(Protocol):
    async def search(self, query: str, *, limit: int) -> tuple[SearchResult, ...]: ...


@dataclass(frozen=True, slots=True)
class SearchEndpoint:
    """Describes any JSON search API without binding to one vendor.

    Vendors differ only in where the query goes, how the key is presented and
    what the result fields are called, so all of that is data rather than code.
    """

    url: str
    query_parameter: str = "q"
    limit_parameter: str | None = "count"
    method: str = "GET"
    # Dotted path to the result array, e.g. "web.results" or "results".
    results_path: str = "results"
    title_field: str = "title"
    url_field: str = "url"
    snippet_field: str = "description"
    api_key_header: str | None = None
    api_key_query_parameter: str | None = None
    extra_parameters: dict[str, str] = field(default_factory=dict)


def _dig(payload: object, path: str) -> object:
    current = payload
    for part in path.split("."):
        if not part:
            continue
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


class HttpSearchProvider:
    def __init__(
        self,
        endpoint: SearchEndpoint,
        *,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.endpoint = endpoint
        self._api_key = api_key
        headers = {"Accept": "application/json"}
        if endpoint.api_key_header and api_key:
            headers[endpoint.api_key_header] = api_key
        self._client = httpx.AsyncClient(
            timeout=timeout,
            transport=transport,
            headers=headers,
        )

    async def search(self, query: str, *, limit: int) -> tuple[SearchResult, ...]:
        parameters: dict[str, str] = dict(self.endpoint.extra_parameters)
        parameters[self.endpoint.query_parameter] = query
        if self.endpoint.limit_parameter:
            parameters[self.endpoint.limit_parameter] = str(limit)
        if self.endpoint.api_key_query_parameter and self._api_key:
            parameters[self.endpoint.api_key_query_parameter] = self._api_key
        try:
            if self.endpoint.method.upper() == "POST":
                response = await self._client.post(
                    self.endpoint.url, json=parameters
                )
            else:
                response = await self._client.get(
                    self.endpoint.url, params=parameters
                )
        except httpx.TimeoutException as error:
            raise SearchError("search request timed out") from error
        except httpx.HTTPError as error:
            raise SearchError(
                f"search request failed: {type(error).__name__}"
            ) from error
        if response.status_code in {401, 403}:
            raise SearchError("search authentication failed")
        if response.status_code == 429:
            raise SearchError("search rate limit exceeded")
        if response.status_code >= 400:
            raise SearchError(f"search returned status {response.status_code}")
        try:
            payload = response.json()
        except ValueError as error:
            raise SearchError("search returned invalid JSON") from error
        rows = _dig(payload, self.endpoint.results_path)
        if not isinstance(rows, list):
            raise SearchError(
                f"search response has no results at '{self.endpoint.results_path}'"
            )
        results = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            url = row.get(self.endpoint.url_field)
            if not isinstance(url, str) or not url:
                continue
            results.append(
                SearchResult(
                    str(row.get(self.endpoint.title_field, "") or ""),
                    url,
                    str(row.get(self.endpoint.snippet_field, "") or ""),
                )
            )
        return tuple(results)

    async def aclose(self) -> None:
        await self._client.aclose()

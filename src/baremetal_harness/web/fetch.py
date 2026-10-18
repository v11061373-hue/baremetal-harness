from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from baremetal_harness.web.guard import UnsafeUrl, UrlGuard
from baremetal_harness.web.html import extract_readable

USER_AGENT = "baremetal_harness/0.1 (+https://github.com/baremetal_harness)"
MAX_REDIRECTS = 5


class FetchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FetchedPage:
    url: str
    status_code: int
    content_type: str
    title: str
    text: str
    links: tuple[tuple[str, str], ...]
    truncated: bool


class WebFetcher:
    def __init__(
        self,
        *,
        guard: UrlGuard | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
        max_bytes: int = 512 * 1024,
    ) -> None:
        self.guard = guard or UrlGuard()
        self.max_bytes = max_bytes
        self._client = httpx.AsyncClient(
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/*"},
        )

    async def fetch(self, url: str) -> FetchedPage:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            self.guard.check(current)
            try:
                response = await self._client.get(current)
            except httpx.TimeoutException as error:
                raise FetchError("request timed out") from error
            except httpx.HTTPError as error:
                raise FetchError(f"request failed: {type(error).__name__}") from error
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise FetchError("redirect without a location header")
                # Re-check the next hop: a redirect is an attacker-controlled
                # way to reach an address the first URL was screened for.
                current = urljoin(current, location)
                continue
            return self._decode(current, response)
        raise FetchError("too many redirects")

    def _decode(self, url: str, response: httpx.Response) -> FetchedPage:
        if response.status_code >= 400:
            raise FetchError(f"server returned status {response.status_code}")
        body = response.content
        truncated = len(body) > self.max_bytes
        if truncated:
            body = body[: self.max_bytes]
        content_type = response.headers.get("content-type", "").split(";")[0].strip()
        text = body.decode(response.encoding or "utf-8", errors="replace")
        if "html" in content_type or text.lstrip()[:1] == "<":
            title, readable, links = extract_readable(text)
        else:
            title, readable, links = "", text.strip(), ()
        return FetchedPage(
            url,
            response.status_code,
            content_type or "text/plain",
            title,
            readable,
            links,
            truncated,
        )

    async def aclose(self) -> None:
        await self._client.aclose()


__all__ = ["WebFetcher", "FetchedPage", "FetchError", "UnsafeUrl"]

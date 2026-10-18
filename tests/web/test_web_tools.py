import httpx
import pytest

from baremetal_harness.permissions.policy import DefaultPermissionPolicy
from baremetal_harness.permissions.types import PermissionDecision
from baremetal_harness.tools.builtin.web import (
    make_fetch_url_tool,
    make_web_search_tool,
)
from baremetal_harness.tools.types import ToolContext
from baremetal_harness.web.fetch import FetchError, WebFetcher
from baremetal_harness.web.guard import UnsafeUrl, UrlGuard
from baremetal_harness.web.html import extract_readable
from baremetal_harness.web.search import (
    HttpSearchProvider,
    SearchEndpoint,
    SearchError,
    SearchResult,
)

PAGE = """<!doctype html>
<html><head><title>  Example  Page </title>
<style>body{color:red}</style><script>var x = "not text";</script></head>
<body><h1>Heading</h1><p>First para.</p><p>Second   para.</p>
<ul><li>alpha</li><li>beta</li></ul>
<a href="/next">Next page</a></body></html>"""


def _public_resolver(host: str, port: int) -> tuple[str, ...]:
    return ("93.184.216.34",)


def _context(tmp_path) -> ToolContext:
    return ToolContext("run-1", "session-1", tmp_path)


def _fetcher(handler, **kwargs) -> WebFetcher:
    return WebFetcher(
        guard=UrlGuard(resolver=_public_resolver),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


# --- HTML extraction ---------------------------------------------------------


def test_extraction_drops_script_and_style_and_keeps_structure() -> None:
    title, text, links = extract_readable(PAGE)

    assert title == "Example Page"
    assert "not text" not in text
    assert "color:red" not in text
    assert "Heading" in text
    assert "First para." in text
    assert "Second para." in text
    assert links == (("Next page", "/next"),)


def test_extraction_separates_block_elements() -> None:
    _, text, _ = extract_readable("<p>one</p><p>two</p>")

    assert text.splitlines() == ["one", "two"]


def test_extraction_decodes_entities() -> None:
    _, text, _ = extract_readable("<p>a &amp; b &lt;c&gt;</p>")

    assert text == "a & b <c>"


# --- SSRF guard --------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1"],
)
def test_guard_blocks_private_and_loopback_targets(address: str) -> None:
    guard = UrlGuard(resolver=lambda host, port: (address,))

    with pytest.raises(UnsafeUrl, match="private or loopback"):
        guard.check("https://internal.invalid/")


def test_guard_blocks_ipv4_mapped_loopback() -> None:
    guard = UrlGuard(resolver=lambda host, port: ("::ffff:127.0.0.1",))

    with pytest.raises(UnsafeUrl, match="private or loopback"):
        guard.check("https://sneaky.invalid/")


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "ftp://example.com/x", "gopher://example.com"],
)
def test_guard_allows_only_http_schemes(url: str) -> None:
    with pytest.raises(UnsafeUrl, match="http"):
        UrlGuard(resolver=_public_resolver).check(url)


def test_guard_rejects_embedded_credentials() -> None:
    with pytest.raises(UnsafeUrl, match="credentials"):
        UrlGuard(resolver=_public_resolver).check("https://user:pw@example.com/")


def test_guard_allows_a_public_address() -> None:
    UrlGuard(resolver=_public_resolver).check("https://example.com/page")


# --- fetching ----------------------------------------------------------------


async def test_fetch_returns_readable_text(tmp_path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"].startswith("baremetal_harness/")
        return httpx.Response(
            200, text=PAGE, headers={"content-type": "text/html; charset=utf-8"}
        )

    tool = make_fetch_url_tool(_fetcher(handler))
    output = await tool.handler(
        {"url": "https://example.com/", "include_links": True}, _context(tmp_path)
    )

    assert "title: Example Page" in output
    assert "First para." in output
    assert "Next page: /next" in output
    assert "not text" not in output


async def test_redirect_hops_are_each_screened(tmp_path) -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/"})
        return httpx.Response(200, text="<p>should never be reached</p>")

    # The redirect target resolves to link-local metadata; only the first host
    # is public, so a guard that checked only the original URL would be fooled.
    fetcher = WebFetcher(
        guard=UrlGuard(
            resolver=lambda host, port: (
                ("93.184.216.34",) if host == "example.com" else ("169.254.169.254",)
            )
        ),
        transport=httpx.MockTransport(handler),
    )
    tool = make_fetch_url_tool(fetcher)

    output = await tool.handler(
        {"url": "https://example.com/start"}, _context(tmp_path)
    )

    assert output.startswith("refused:")
    assert "private or loopback" in output
    assert seen == ["https://example.com/start"]


async def test_fetch_reports_http_errors(tmp_path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="missing")

    tool = make_fetch_url_tool(_fetcher(handler))
    output = await tool.handler({"url": "https://example.com/"}, _context(tmp_path))

    assert output == "fetch failed: server returned status 404"


async def test_oversized_body_is_truncated(tmp_path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="x" * 5000, headers={"content-type": "text/plain"})

    tool = make_fetch_url_tool(_fetcher(handler, max_bytes=1000))
    output = await tool.handler({"url": "https://example.com/"}, _context(tmp_path))

    assert "content was truncated" in output


async def test_redirect_loop_is_bounded(tmp_path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://example.com/loop"})

    with pytest.raises(FetchError, match="too many redirects"):
        await _fetcher(handler).fetch("https://example.com/loop")


# --- search ------------------------------------------------------------------


async def test_search_maps_a_vendor_shaped_response(tmp_path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["query"] == "agent harness"
        assert request.url.params["n"] == "2"
        assert request.headers["x-api-key"] == "secret-key"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {"name": "First", "link": "https://a.invalid", "blurb": "A"},
                        {"name": "Second", "link": "https://b.invalid", "blurb": "B"},
                    ]
                }
            },
        )

    provider = HttpSearchProvider(
        SearchEndpoint(
            url="https://search.invalid/v1",
            query_parameter="query",
            limit_parameter="n",
            results_path="web.results",
            title_field="name",
            url_field="link",
            snippet_field="blurb",
            api_key_header="X-Api-Key",
        ),
        api_key="secret-key",
        transport=httpx.MockTransport(handler),
    )
    output = await make_web_search_tool(provider).handler(
        {"query": "agent harness", "limit": 2}, _context(tmp_path)
    )
    await provider.aclose()

    assert "1. First" in output
    assert "https://a.invalid" in output
    assert "2. Second" in output


async def test_search_authentication_failure_is_reported(tmp_path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={})

    provider = HttpSearchProvider(
        SearchEndpoint(url="https://search.invalid/v1"),
        transport=httpx.MockTransport(handler),
    )
    output = await make_web_search_tool(provider).handler(
        {"query": "x"}, _context(tmp_path)
    )
    await provider.aclose()

    assert output == "search failed: search authentication failed"


async def test_search_rejects_a_response_without_results(tmp_path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    provider = HttpSearchProvider(
        SearchEndpoint(url="https://search.invalid/v1"),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(SearchError, match="no results at"):
        await provider.search("x", limit=3)
    await provider.aclose()


async def test_search_limit_is_bounded(tmp_path) -> None:
    class Unused:
        async def search(self, query: str, *, limit: int):
            raise AssertionError("must not be called")

    with pytest.raises(ValueError, match="limit"):
        await make_web_search_tool(Unused()).handler(
            {"query": "x", "limit": 999}, _context(tmp_path)
        )


async def test_search_result_rows_without_a_url_are_skipped(tmp_path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [{"title": "no url"}, {"title": "ok", "url": "https://x.invalid"}]},
        )

    provider = HttpSearchProvider(
        SearchEndpoint(url="https://search.invalid/v1", snippet_field="snippet"),
        transport=httpx.MockTransport(handler),
    )
    results = await provider.search("x", limit=5)
    await provider.aclose()

    assert results == (SearchResult("ok", "https://x.invalid", ""),)


# --- permissions -------------------------------------------------------------


def test_network_tools_always_require_approval() -> None:
    class Unused:
        async def search(self, query: str, *, limit: int):
            raise AssertionError("must not be called")

    for tool in (
        make_fetch_url_tool(WebFetcher()),
        make_web_search_tool(Unused()),
    ):
        result = DefaultPermissionPolicy().evaluate(
            tool_name=tool.spec.name,
            capabilities=tool.spec.capabilities,
            arguments={},
        )
        assert result.decision is PermissionDecision.ASK
        assert result.reason == "unrestricted network"

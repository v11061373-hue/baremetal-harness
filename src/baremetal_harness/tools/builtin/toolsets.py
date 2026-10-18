from baremetal_harness.tools.builtin.git import make_git_tools
from baremetal_harness.tools.builtin.web import (
    make_fetch_url_tool,
    make_web_search_tool,
)
from baremetal_harness.tools.types import RegisteredTool
from baremetal_harness.web.fetch import WebFetcher
from baremetal_harness.web.search import HttpSearchProvider, SearchEndpoint


def make_local_inspection_tools(sandbox) -> tuple[RegisteredTool, ...]:
    """Read-only tools that never leave the machine."""
    return make_git_tools(sandbox)


def make_web_tools(
    *,
    fetcher: WebFetcher | None = None,
    search_endpoint: SearchEndpoint | None = None,
    search_api_key: str | None = None,
) -> tuple[tuple[RegisteredTool, ...], tuple[object, ...]]:
    """Build the network tools plus the resources that must be closed later.

    web_search only exists when an endpoint is configured: advertising a search
    tool with nowhere to send the query would make the model plan around a
    capability that always fails.
    """
    resolved_fetcher = fetcher or WebFetcher()
    tools = [make_fetch_url_tool(resolved_fetcher)]
    closeables: list[object] = [resolved_fetcher]
    if search_endpoint is not None:
        provider = HttpSearchProvider(search_endpoint, api_key=search_api_key)
        tools.append(make_web_search_tool(provider))
        closeables.append(provider)
    return tuple(tools), tuple(closeables)

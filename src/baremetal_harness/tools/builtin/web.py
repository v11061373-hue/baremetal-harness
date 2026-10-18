from baremetal_harness.tools.types import (
    RegisteredTool,
    RiskLevel,
    ToolCapabilities,
    ToolContext,
    ToolSpec,
)
from baremetal_harness.web.fetch import FetchError, WebFetcher
from baremetal_harness.web.guard import UnsafeUrl
from baremetal_harness.web.search import SearchError, SearchProvider

MAX_TEXT_CHARACTERS = 20_000
MAX_LINKS = 50
MAX_SEARCH_RESULTS = 20

# Network egress is never auto-approved: the policy turns "unrestricted"
# into an explicit ask so a human sees that the agent is leaving the machine.
NETWORK_READ = ToolCapabilities(
    filesystem="none",
    network="unrestricted",
    subprocess=False,
    risk_level=RiskLevel.MEDIUM,
    side_effects=False,
    idempotent=True,
)


def make_fetch_url_tool(fetcher: WebFetcher) -> RegisteredTool:
    async def fetch_url(arguments, context: ToolContext) -> str:
        try:
            page = await fetcher.fetch(str(arguments["url"]))
        except UnsafeUrl as error:
            return f"refused: {error}"
        except FetchError as error:
            return f"fetch failed: {error}"
        text = page.text
        truncated = page.truncated
        if len(text) > MAX_TEXT_CHARACTERS:
            text = text[:MAX_TEXT_CHARACTERS]
            truncated = True
        lines = [f"url: {page.url}", f"status: {page.status_code}"]
        if page.title:
            lines.append(f"title: {page.title}")
        if truncated:
            lines.append("note: content was truncated")
        if bool(arguments.get("include_links", False)) and page.links:
            lines.append("links:")
            lines += [
                f"  - {label or '(no text)'}: {href}"
                for label, href in page.links[:MAX_LINKS]
            ]
        lines.append("")
        lines.append(text)
        return "\n".join(lines)

    return RegisteredTool(
        ToolSpec(
            "fetch_url",
            "Fetch an http(s) page and return its readable text",
            {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "include_links": {"type": "boolean"},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            NETWORK_READ,
        ),
        fetch_url,
    )


def make_web_search_tool(provider: SearchProvider) -> RegisteredTool:
    async def web_search(arguments, context: ToolContext) -> str:
        limit = int(arguments.get("limit", 5))
        if not 1 <= limit <= MAX_SEARCH_RESULTS:
            raise ValueError(f"limit must be between 1 and {MAX_SEARCH_RESULTS}")
        try:
            results = await provider.search(str(arguments["query"]), limit=limit)
        except SearchError as error:
            return f"search failed: {error}"
        if not results:
            return "no results"
        return "\n".join(
            f"{index}. {result.title}\n   {result.url}\n   {result.snippet}".rstrip()
            for index, result in enumerate(results, start=1)
        )

    return RegisteredTool(
        ToolSpec(
            "web_search",
            "Search the web and return ranked result titles, URLs and snippets",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            NETWORK_READ,
        ),
        web_search,
    )

from typing import Any

import httpx

from micro_x_agent_loop.tools.web.search_provider import SearchProvider

_DEFAULT_COUNT = 5


class WebSearchTool:
    def __init__(self, provider: SearchProvider) -> None:
        self._provider = provider

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web and return a list of results with titles, URLs, "
            "and descriptions. Use this to discover URLs before fetching "
            "their full content with web_fetch."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (max 400 characters)",
                },
                "count": {
                    "type": "number",
                    "description": "Number of results to return (1–20, default 5)",
                },
            },
            "required": ["query"],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        query: str = tool_input.get("query", "").strip()
        if not query:
            return "Error: query must not be empty"

        query = query[:400]
        count = int(tool_input.get("count", _DEFAULT_COUNT))
        count = max(1, min(20, count))

        try:
            results = await self._provider.search(query, count)
        except httpx.TimeoutException:
            return "Error: Search request timed out"
        except httpx.HTTPStatusError as ex:
            return f"Error: {ex.message if hasattr(ex, 'message') else ex}"
        except httpx.HTTPError as ex:
            return f"Error: {ex}"

        if not results:
            return f"No results found for: {query}"

        lines = [f'Search: "{query}"', f"Results: {len(results)}", ""]
        for i, result in enumerate(results, 1):
            lines.append(f"{i}. {result.title}")
            lines.append(f"   {result.url}")
            if result.description:
                lines.append(f"   {result.description}")
            lines.append("")

        return "\n".join(lines).rstrip()

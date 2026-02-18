import httpx

from micro_x_agent_loop.tools.web.search_provider import SearchResult

_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
_TIMEOUT_SECONDS = 30


class BraveSearchProvider:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @property
    def provider_name(self) -> str:
        return "Brave"

    async def search(self, query: str, count: int) -> list[SearchResult]:
        headers = {
            "X-Subscription-Token": self._api_key,
            "Accept": "application/json",
        }
        params = {"q": query, "count": count}

        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.get(
                _BRAVE_SEARCH_URL, headers=headers, params=params
            )

        if response.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {response.status_code} from Brave Search API",
                request=response.request,
                response=response,
            )

        data = response.json()
        raw_results = data.get("web", {}).get("results", [])

        return [
            SearchResult(
                title=r.get("title", "(no title)"),
                url=r.get("url", ""),
                description=r.get("description", ""),
            )
            for r in raw_results
        ]

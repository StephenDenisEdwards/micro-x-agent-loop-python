import httpx

_client: httpx.AsyncClient | None = None


async def get_github_client(token: str) -> httpx.AsyncClient:
    global _client
    if _client is not None:
        return _client
    _client = httpx.AsyncClient(
        base_url="https://api.github.com",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30.0,
    )
    return _client

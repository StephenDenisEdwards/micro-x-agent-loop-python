from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    description: str


@runtime_checkable
class SearchProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    async def search(self, query: str, count: int) -> list[SearchResult]:
        """Return search results. Raises on errors (caller handles formatting)."""
        ...

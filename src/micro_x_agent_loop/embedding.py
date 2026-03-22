"""Embedding client and vector index for semantic tool search.

Uses Ollama's native ``/api/embed`` endpoint to generate dense embeddings
for tool descriptions and search queries.  Cosine similarity is computed
in pure Python (no numpy) — sufficient for ~100 tool vectors.
"""

from __future__ import annotations

import math
from typing import Any

import httpx
from loguru import logger

# ---------------------------------------------------------------------------
# Cosine similarity (pure Python)
# ---------------------------------------------------------------------------

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Returns 0.0 if either vector has zero magnitude.
    """
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for ai, bi in zip(a, b, strict=False):
        dot += ai * bi
        norm_a += ai * ai
        norm_b += bi * bi
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


# ---------------------------------------------------------------------------
# Ollama embedding client
# ---------------------------------------------------------------------------

class OllamaEmbeddingClient:
    """Async client for Ollama's native embedding API."""

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts via ``POST /api/embed``.

        Returns a list of embedding vectors (one per input text).
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self._base_url}/api/embed",
                json={"model": self._model, "input": texts},
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            embeddings: list[list[float]] = data["embeddings"]
            return embeddings

    async def is_available(self) -> bool:
        """Check if the embedding model is available."""
        try:
            result = await self.embed(["test"])
            return len(result) > 0 and len(result[0]) > 0
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Tool embedding index
# ---------------------------------------------------------------------------

# Search hints for tools whose descriptions don't mention common use cases.
# These are appended to the embedding text to improve semantic search recall.
_TOOL_SEARCH_HINTS: dict[str, str] = {
    "filesystem__bash": (
        "list files, directory listing, dir, ls, run command, "
        "create directory, move files, copy files, delete files, find files"
    ),
    "google__gmail_search": (
        "list emails, read emails, inbox, email search, "
        "find emails, check email, latest emails, recent emails"
    ),
    "google__calendar_list_events": (
        "list calendar, schedule, meetings, appointments, events today"
    ),
    "google__contacts_list": (
        "list contacts, phone numbers, address book"
    ),
}


def _build_embedding_text(name: str, description: str) -> str:
    """Build enriched text for embedding a tool.

    Splits the tool name (e.g. ``filesystem__bash``) into readable words
    (``filesystem bash``) and prepends them so the embedding captures the
    tool's namespace/category alongside its description.  Appends any
    search hints defined in ``_TOOL_SEARCH_HINTS``.
    """
    # "filesystem__bash" → "filesystem bash"
    readable_name = name.replace("__", " ").replace("_", " ")
    text = f"{readable_name}: {description}"
    hints = _TOOL_SEARCH_HINTS.get(name)
    if hints:
        text += f". Common uses: {hints}"
    return text


class ToolEmbeddingIndex:
    """In-memory vector index for tool descriptions.

    Build once at startup, then search by cosine similarity.
    """

    def __init__(self, client: OllamaEmbeddingClient) -> None:
        self._client = client
        self._tool_embeddings: dict[str, list[float]] = {}

    async def build(self, tools: list[tuple[str, str]]) -> bool:
        """Embed all tools and store in the index.

        Args:
            tools: List of ``(name, description)`` pairs.

        Returns:
            ``True`` if the index was built successfully, ``False`` on error.
        """
        if not tools:
            return False

        texts = [_build_embedding_text(name, desc) for name, desc in tools]
        names = [name for name, _ in tools]

        try:
            embeddings = await self._client.embed(texts)
            if len(embeddings) != len(names):
                logger.warning(
                    f"Embedding count mismatch: expected {len(names)}, got {len(embeddings)}"
                )
                return False

            self._tool_embeddings = dict(zip(names, embeddings, strict=True))
            logger.info(
                f"Tool embedding index built: {len(self._tool_embeddings)} tools, "
                f"dimension={len(embeddings[0]) if embeddings else 0}"
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to build tool embedding index: {e}")
            return False

    def search(self, query_embedding: list[float], top_k: int) -> list[tuple[str, float]]:
        """Find the top-k most similar tools to the query embedding.

        Returns:
            List of ``(tool_name, similarity_score)`` sorted by descending score.
        """
        scores: list[tuple[str, float]] = []
        for name, tool_embedding in self._tool_embeddings.items():
            score = cosine_similarity(query_embedding, tool_embedding)
            scores.append((name, score))
        scores.sort(key=lambda x: (-x[1], x[0]))
        return scores[:top_k]

    @property
    def is_ready(self) -> bool:
        """True if the index has been built with at least one tool."""
        return len(self._tool_embeddings) > 0

    def remove_tools(self, tool_names: list[str]) -> None:
        """Remove tools from the index after live deletion."""
        for name in tool_names:
            self._tool_embeddings.pop(name, None)

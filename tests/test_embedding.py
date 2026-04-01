"""Tests for embedding.py — cosine similarity, Ollama client, and vector indices."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from micro_x_agent_loop.embedding import (
    OllamaEmbeddingClient,
    TaskEmbeddingIndex,
    ToolEmbeddingIndex,
    _build_embedding_text,
    cosine_similarity,
)

# ---------------------------------------------------------------------------
# cosine_similarity
# ---------------------------------------------------------------------------


class CosineSimTests(unittest.TestCase):
    def test_identical_vectors(self) -> None:
        self.assertAlmostEqual(1.0, cosine_similarity([1, 0], [1, 0]))

    def test_orthogonal_vectors(self) -> None:
        self.assertAlmostEqual(0.0, cosine_similarity([1, 0], [0, 1]))

    def test_opposite_vectors(self) -> None:
        self.assertAlmostEqual(-1.0, cosine_similarity([1, 0], [-1, 0]))

    def test_zero_vector_a(self) -> None:
        self.assertAlmostEqual(0.0, cosine_similarity([0, 0], [1, 1]))

    def test_zero_vector_b(self) -> None:
        self.assertAlmostEqual(0.0, cosine_similarity([1, 1], [0, 0]))

    def test_both_zero(self) -> None:
        self.assertAlmostEqual(0.0, cosine_similarity([0, 0], [0, 0]))

    def test_known_value(self) -> None:
        # [1,2,3] · [4,5,6] = 32, |a|=√14, |b|=√77
        import math
        expected = 32 / (math.sqrt(14) * math.sqrt(77))
        self.assertAlmostEqual(expected, cosine_similarity([1, 2, 3], [4, 5, 6]), places=6)


# ---------------------------------------------------------------------------
# _build_embedding_text
# ---------------------------------------------------------------------------


class BuildEmbeddingTextTests(unittest.TestCase):
    def test_plain_name(self) -> None:
        text = _build_embedding_text("my_tool", "Does stuff")
        self.assertIn("my tool", text)
        self.assertIn("Does stuff", text)

    def test_double_underscore(self) -> None:
        text = _build_embedding_text("filesystem__bash", "Run shell commands")
        self.assertIn("filesystem bash", text)

    def test_search_hints_appended(self) -> None:
        text = _build_embedding_text("filesystem__bash", "Run shell commands")
        self.assertIn("Common uses:", text)
        self.assertIn("list files", text)

    def test_no_hints_for_unknown_tool(self) -> None:
        text = _build_embedding_text("unknown_tool", "desc")
        self.assertNotIn("Common uses:", text)


# ---------------------------------------------------------------------------
# OllamaEmbeddingClient
# ---------------------------------------------------------------------------


class OllamaEmbeddingClientTests(unittest.TestCase):
    def test_init_strips_trailing_slash(self) -> None:
        client = OllamaEmbeddingClient("http://localhost:11434/", "model")
        self.assertEqual("http://localhost:11434", client._base_url)

    def test_embed_calls_api(self) -> None:
        client = OllamaEmbeddingClient("http://localhost:11434", "nomic-embed")

        mock_response = MagicMock()
        mock_response.json.return_value = {"embeddings": [[0.1, 0.2], [0.3, 0.4]]}
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("micro_x_agent_loop.embedding.httpx.AsyncClient", return_value=mock_http):
            result = asyncio.run(client.embed(["hello", "world"]))

        self.assertEqual([[0.1, 0.2], [0.3, 0.4]], result)
        mock_http.post.assert_called_once()
        call_args = mock_http.post.call_args
        self.assertIn("/api/embed", call_args[0][0])

    def test_is_available_true(self) -> None:
        client = OllamaEmbeddingClient("http://localhost:11434", "nomic-embed")

        mock_response = MagicMock()
        mock_response.json.return_value = {"embeddings": [[0.1, 0.2]]}
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("micro_x_agent_loop.embedding.httpx.AsyncClient", return_value=mock_http):
            self.assertTrue(asyncio.run(client.is_available()))

    def test_is_available_false_on_error(self) -> None:
        client = OllamaEmbeddingClient("http://localhost:11434", "nomic-embed")

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=Exception("connection refused"))
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("micro_x_agent_loop.embedding.httpx.AsyncClient", return_value=mock_http):
            self.assertFalse(asyncio.run(client.is_available()))

    def test_is_available_false_on_empty(self) -> None:
        client = OllamaEmbeddingClient("http://localhost:11434", "nomic-embed")

        mock_response = MagicMock()
        mock_response.json.return_value = {"embeddings": []}
        mock_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("micro_x_agent_loop.embedding.httpx.AsyncClient", return_value=mock_http):
            self.assertFalse(asyncio.run(client.is_available()))


# ---------------------------------------------------------------------------
# ToolEmbeddingIndex
# ---------------------------------------------------------------------------


class ToolEmbeddingIndexTests(unittest.TestCase):
    def _make_index(self, embed_result: list[list[float]] | None = None) -> ToolEmbeddingIndex:
        client = MagicMock()
        if embed_result is not None:
            client.embed = AsyncMock(return_value=embed_result)
        else:
            client.embed = AsyncMock(return_value=[[0.1, 0.9], [0.9, 0.1]])
        return ToolEmbeddingIndex(client)

    def test_not_ready_initially(self) -> None:
        idx = self._make_index()
        self.assertFalse(idx.is_ready)

    def test_build_success(self) -> None:
        idx = self._make_index()
        result = asyncio.run(idx.build([("tool_a", "desc a"), ("tool_b", "desc b")]))
        self.assertTrue(result)
        self.assertTrue(idx.is_ready)

    def test_build_empty_tools(self) -> None:
        idx = self._make_index()
        result = asyncio.run(idx.build([]))
        self.assertFalse(result)
        self.assertFalse(idx.is_ready)

    def test_build_mismatch_count(self) -> None:
        idx = self._make_index(embed_result=[[0.1, 0.2]])  # 1 embedding for 2 tools
        result = asyncio.run(idx.build([("a", "da"), ("b", "db")]))
        self.assertFalse(result)

    def test_build_exception(self) -> None:
        idx = self._make_index()
        idx._client.embed = AsyncMock(side_effect=Exception("api error"))
        result = asyncio.run(idx.build([("a", "da")]))
        self.assertFalse(result)

    def test_search(self) -> None:
        idx = self._make_index(embed_result=[[1.0, 0.0], [0.0, 1.0]])
        asyncio.run(idx.build([("tool_a", "desc a"), ("tool_b", "desc b")]))
        results = idx.search([1.0, 0.0], top_k=2)
        self.assertEqual(2, len(results))
        # tool_a should be first (identical vector)
        self.assertEqual("tool_a", results[0][0])
        self.assertAlmostEqual(1.0, results[0][1])

    def test_search_top_k(self) -> None:
        idx = self._make_index(embed_result=[[1.0, 0.0], [0.5, 0.5], [0.0, 1.0]])
        asyncio.run(idx.build([("a", "da"), ("b", "db"), ("c", "dc")]))
        results = idx.search([1.0, 0.0], top_k=1)
        self.assertEqual(1, len(results))

    def test_remove_tools(self) -> None:
        idx = self._make_index(embed_result=[[1.0, 0.0], [0.0, 1.0]])
        asyncio.run(idx.build([("tool_a", "desc a"), ("tool_b", "desc b")]))
        idx.remove_tools(["tool_a"])
        results = idx.search([1.0, 0.0], top_k=10)
        names = [r[0] for r in results]
        self.assertNotIn("tool_a", names)


# ---------------------------------------------------------------------------
# TaskEmbeddingIndex
# ---------------------------------------------------------------------------


class TaskEmbeddingIndexTests(unittest.TestCase):
    def _make_index(self, dim: int = 4) -> TaskEmbeddingIndex:
        client = MagicMock()
        # Return unique vectors for each task type
        call_count = 0

        async def mock_embed(texts: list[str]) -> list[list[float]]:
            nonlocal call_count
            result = []
            for i in range(len(texts)):
                vec = [0.0] * dim
                vec[i % dim] = 1.0
                result.append(vec)
            return result

        client.embed = mock_embed
        return TaskEmbeddingIndex(client)

    def test_not_ready_initially(self) -> None:
        client = MagicMock()
        idx = TaskEmbeddingIndex(client)
        self.assertFalse(idx.is_ready)

    def test_build_success(self) -> None:
        idx = self._make_index(dim=10)
        result = asyncio.run(idx.build())
        self.assertTrue(result)
        self.assertTrue(idx.is_ready)

    def test_build_mismatch(self) -> None:
        client = MagicMock()
        client.embed = AsyncMock(return_value=[[0.1]])  # Wrong count
        idx = TaskEmbeddingIndex(client)
        result = asyncio.run(idx.build())
        self.assertFalse(result)

    def test_build_exception(self) -> None:
        client = MagicMock()
        client.embed = AsyncMock(side_effect=Exception("fail"))
        idx = TaskEmbeddingIndex(client)
        result = asyncio.run(idx.build())
        self.assertFalse(result)

    def test_classify(self) -> None:
        idx = self._make_index(dim=10)
        asyncio.run(idx.build())
        task_type, score = idx.classify([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        self.assertIsInstance(task_type, str)
        self.assertGreater(score, 0.0)

    def test_classify_empty_index(self) -> None:
        client = MagicMock()
        idx = TaskEmbeddingIndex(client)
        task_type, score = idx.classify([1.0, 0.0])
        self.assertEqual("conversational", task_type)
        self.assertEqual(0.0, score)

    def test_embed_query_success(self) -> None:
        client = MagicMock()
        client.embed = AsyncMock(return_value=[[0.5, 0.5]])
        idx = TaskEmbeddingIndex(client)
        result = asyncio.run(idx.embed_query("hello"))
        self.assertEqual([0.5, 0.5], result)

    def test_embed_query_empty_result(self) -> None:
        client = MagicMock()
        client.embed = AsyncMock(return_value=[])
        idx = TaskEmbeddingIndex(client)
        result = asyncio.run(idx.embed_query("hello"))
        self.assertIsNone(result)

    def test_embed_query_exception(self) -> None:
        client = MagicMock()
        client.embed = AsyncMock(side_effect=Exception("fail"))
        idx = TaskEmbeddingIndex(client)
        result = asyncio.run(idx.embed_query("hello"))
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

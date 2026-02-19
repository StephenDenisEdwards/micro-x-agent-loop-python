import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from micro_x_agent_loop.tools.github.github_search_code_tool import GitHubSearchCodeTool


def _make_response(status_code: int, json_data: object) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = json.dumps(json_data) if isinstance(json_data, (dict, list)) else str(json_data)
    return resp


class TestGitHubSearchCodeTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = GitHubSearchCodeTool("fake-token")

    # -- properties --

    def test_name(self) -> None:
        self.assertEqual(self.tool.name, "github_search_code")

    def test_is_not_mutating(self) -> None:
        self.assertFalse(self.tool.is_mutating)

    def test_required_params(self) -> None:
        self.assertEqual(self.tool.input_schema["required"], ["query"])

    # -- execute: basic search --

    @patch("micro_x_agent_loop.tools.github.github_search_code_tool.get_github_client")
    def test_execute_basic(self, mock_get_client: AsyncMock) -> None:
        api_data = {
            "total_count": 1,
            "items": [
                {
                    "repository": {"full_name": "owner/repo"},
                    "path": "src/utils.py",
                    "text_matches": [{"fragment": "def hello_world():"}],
                }
            ],
        }

        client = AsyncMock()
        client.get.return_value = _make_response(200, api_data)
        mock_get_client.return_value = client

        result = asyncio.run(
            self.tool.execute({"query": "hello_world"})
        )

        self.assertIn("Code search: 1 of 1 result(s)", result)
        self.assertIn("owner/repo -- src/utils.py", result)
        self.assertIn("def hello_world():", result)

        call_kwargs = client.get.call_args
        self.assertEqual(call_kwargs.args[0], "/search/code")
        self.assertEqual(call_kwargs.kwargs["params"]["q"], "hello_world")

    # -- execute: with repo and language filters --

    @patch("micro_x_agent_loop.tools.github.github_search_code_tool.get_github_client")
    def test_execute_with_filters(self, mock_get_client: AsyncMock) -> None:
        api_data = {"total_count": 0, "items": []}

        client = AsyncMock()
        client.get.return_value = _make_response(200, api_data)
        mock_get_client.return_value = client

        result = asyncio.run(
            self.tool.execute({
                "query": "func",
                "repo": "owner/repo",
                "language": "python",
                "maxResults": 5,
            })
        )

        self.assertIn("0 results", result)

        call_kwargs = client.get.call_args
        q = call_kwargs.kwargs["params"]["q"]
        self.assertIn("repo:owner/repo", q)
        self.assertIn("language:python", q)
        self.assertEqual(call_kwargs.kwargs["params"]["per_page"], 5)

    # -- execute: text_match accept header --

    @patch("micro_x_agent_loop.tools.github.github_search_code_tool.get_github_client")
    def test_execute_sends_text_match_header(self, mock_get_client: AsyncMock) -> None:
        api_data = {"total_count": 0, "items": []}

        client = AsyncMock()
        client.get.return_value = _make_response(200, api_data)
        mock_get_client.return_value = client

        asyncio.run(
            self.tool.execute({"query": "test"})
        )

        call_kwargs = client.get.call_args
        self.assertIn("application/vnd.github.text-match+json", call_kwargs.kwargs["headers"]["Accept"])

    # -- execute: maxResults capped at 20 --

    @patch("micro_x_agent_loop.tools.github.github_search_code_tool.get_github_client")
    def test_max_results_capped(self, mock_get_client: AsyncMock) -> None:
        api_data = {"total_count": 0, "items": []}

        client = AsyncMock()
        client.get.return_value = _make_response(200, api_data)
        mock_get_client.return_value = client

        asyncio.run(
            self.tool.execute({"query": "test", "maxResults": 100})
        )

        call_kwargs = client.get.call_args
        self.assertEqual(call_kwargs.kwargs["params"]["per_page"], 20)

    # -- execute: API error --

    @patch("micro_x_agent_loop.tools.github.github_search_code_tool.get_github_client")
    def test_execute_api_error(self, mock_get_client: AsyncMock) -> None:
        client = AsyncMock()
        client.get.return_value = _make_response(403, {"message": "rate limit"})
        mock_get_client.return_value = client

        result = asyncio.run(
            self.tool.execute({"query": "test"})
        )

        self.assertIn("GitHub API error: HTTP 403", result)

    # -- execute: exception --

    @patch("micro_x_agent_loop.tools.github.github_search_code_tool.get_github_client")
    def test_execute_exception(self, mock_get_client: AsyncMock) -> None:
        mock_get_client.side_effect = RuntimeError("boom")

        result = asyncio.run(
            self.tool.execute({"query": "test"})
        )

        self.assertIn("Error searching code:", result)
        self.assertIn("boom", result)

    # -- fragment truncation --

    @patch("micro_x_agent_loop.tools.github.github_search_code_tool.get_github_client")
    def test_long_fragment_truncated(self, mock_get_client: AsyncMock) -> None:
        api_data = {
            "total_count": 1,
            "items": [
                {
                    "repository": {"full_name": "o/r"},
                    "path": "big.py",
                    "text_matches": [{"fragment": "x" * 300}],
                }
            ],
        }

        client = AsyncMock()
        client.get.return_value = _make_response(200, api_data)
        mock_get_client.return_value = client

        result = asyncio.run(
            self.tool.execute({"query": "x"})
        )

        self.assertIn("...", result)

    # -- no text_matches --

    @patch("micro_x_agent_loop.tools.github.github_search_code_tool.get_github_client")
    def test_no_text_matches(self, mock_get_client: AsyncMock) -> None:
        api_data = {
            "total_count": 1,
            "items": [
                {
                    "repository": {"full_name": "o/r"},
                    "path": "a.py",
                }
            ],
        }

        client = AsyncMock()
        client.get.return_value = _make_response(200, api_data)
        mock_get_client.return_value = client

        result = asyncio.run(
            self.tool.execute({"query": "test"})
        )

        self.assertIn("o/r -- a.py", result)

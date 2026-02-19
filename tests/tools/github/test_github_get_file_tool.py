import asyncio
import base64
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from micro_x_agent_loop.tools.github.github_get_file_tool import GitHubGetFileTool


def _make_response(status_code: int, json_data: object) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = json.dumps(json_data) if isinstance(json_data, (dict, list)) else str(json_data)
    return resp


class TestGitHubGetFileTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = GitHubGetFileTool("fake-token")

    # -- properties --

    def test_name(self) -> None:
        self.assertEqual(self.tool.name, "github_get_file")

    def test_is_not_mutating(self) -> None:
        self.assertFalse(self.tool.is_mutating)

    def test_required_params(self) -> None:
        self.assertEqual(self.tool.input_schema["required"], ["repo", "path"])

    # -- execute: file --

    @patch("micro_x_agent_loop.tools.github.github_get_file_tool.get_github_client")
    def test_execute_file(self, mock_get_client: AsyncMock) -> None:
        content = "print('hello')\n"
        encoded = base64.b64encode(content.encode()).decode()
        api_data = {"type": "file", "content": encoded, "size": len(content)}

        client = AsyncMock()
        client.get.return_value = _make_response(200, api_data)
        mock_get_client.return_value = client

        result = asyncio.run(
            self.tool.execute({"repo": "owner/repo", "path": "hello.py"})
        )

        self.assertIn("File: owner/repo/hello.py", result)
        self.assertIn("print('hello')", result)
        client.get.assert_called_once_with("/repos/owner/repo/contents/hello.py", params={})

    @patch("micro_x_agent_loop.tools.github.github_get_file_tool.get_github_client")
    def test_execute_file_with_ref(self, mock_get_client: AsyncMock) -> None:
        encoded = base64.b64encode(b"data").decode()
        api_data = {"type": "file", "content": encoded, "size": 4}

        client = AsyncMock()
        client.get.return_value = _make_response(200, api_data)
        mock_get_client.return_value = client

        result = asyncio.run(
            self.tool.execute({"repo": "owner/repo", "path": "f.txt", "ref": "dev"})
        )

        self.assertIn("(ref: dev)", result)
        client.get.assert_called_once_with("/repos/owner/repo/contents/f.txt", params={"ref": "dev"})

    # -- execute: directory --

    @patch("micro_x_agent_loop.tools.github.github_get_file_tool.get_github_client")
    def test_execute_directory(self, mock_get_client: AsyncMock) -> None:
        api_data = [
            {"name": "src", "type": "dir", "size": 0},
            {"name": "README.md", "type": "file", "size": 512},
        ]

        client = AsyncMock()
        client.get.return_value = _make_response(200, api_data)
        mock_get_client.return_value = client

        result = asyncio.run(
            self.tool.execute({"repo": "owner/repo", "path": "."})
        )

        self.assertIn("Directory: owner/repo/.", result)
        self.assertIn("2 entries", result)
        self.assertIn("src/", result)
        self.assertIn("README.md", result)

    # -- execute: API error --

    @patch("micro_x_agent_loop.tools.github.github_get_file_tool.get_github_client")
    def test_execute_api_error(self, mock_get_client: AsyncMock) -> None:
        client = AsyncMock()
        client.get.return_value = _make_response(404, {"message": "Not Found"})
        mock_get_client.return_value = client

        result = asyncio.run(
            self.tool.execute({"repo": "owner/repo", "path": "missing.txt"})
        )

        self.assertIn("GitHub API error: HTTP 404", result)

    # -- execute: exception --

    @patch("micro_x_agent_loop.tools.github.github_get_file_tool.get_github_client")
    def test_execute_exception(self, mock_get_client: AsyncMock) -> None:
        mock_get_client.side_effect = RuntimeError("connection failed")

        result = asyncio.run(
            self.tool.execute({"repo": "owner/repo", "path": "f.txt"})
        )

        self.assertIn("Error getting file:", result)
        self.assertIn("connection failed", result)

    # -- truncation --

    @patch("micro_x_agent_loop.tools.github.github_get_file_tool.get_github_client")
    def test_execute_truncates_large_file(self, mock_get_client: AsyncMock) -> None:
        big_content = "x" * 150_000
        encoded = base64.b64encode(big_content.encode()).decode()
        api_data = {"type": "file", "content": encoded, "size": len(big_content)}

        client = AsyncMock()
        client.get.return_value = _make_response(200, api_data)
        mock_get_client.return_value = client

        result = asyncio.run(
            self.tool.execute({"repo": "owner/repo", "path": "big.txt"})
        )

        self.assertIn("... truncated", result)
        # Content portion should be capped at 100k + truncation suffix
        self.assertLess(len(result), 110_000)

    # -- path stripping --

    @patch("micro_x_agent_loop.tools.github.github_get_file_tool.get_github_client")
    def test_path_strips_slashes(self, mock_get_client: AsyncMock) -> None:
        encoded = base64.b64encode(b"ok").decode()
        api_data = {"type": "file", "content": encoded, "size": 2}

        client = AsyncMock()
        client.get.return_value = _make_response(200, api_data)
        mock_get_client.return_value = client

        asyncio.run(
            self.tool.execute({"repo": "o/r", "path": "/src/main.py/"})
        )

        client.get.assert_called_once_with("/repos/o/r/contents/src/main.py", params={})

    # -- human_size --

    def test_human_size_bytes(self) -> None:
        self.assertEqual(GitHubGetFileTool._human_size(500), "500 B")

    def test_human_size_kb(self) -> None:
        self.assertEqual(GitHubGetFileTool._human_size(2560), "2.5 KB")

    def test_human_size_mb(self) -> None:
        self.assertEqual(GitHubGetFileTool._human_size(2 * 1024 * 1024), "2.0 MB")

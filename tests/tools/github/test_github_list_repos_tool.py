import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from micro_x_agent_loop.tools.github.github_list_repos_tool import GitHubListReposTool


def _make_response(status_code: int, json_data: object) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = json.dumps(json_data) if isinstance(json_data, (dict, list)) else str(json_data)
    return resp


def _sample_repo(
    full_name: str = "owner/my-repo",
    description: str = "A cool project",
    private: bool = False,
    language: str = "Python",
    stars: int = 42,
    updated: str = "2026-02-19T10:00:00Z",
) -> dict:
    return {
        "full_name": full_name,
        "description": description,
        "private": private,
        "language": language,
        "stargazers_count": stars,
        "updated_at": updated,
    }


class TestGitHubListReposTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = GitHubListReposTool("fake-token")

    # -- properties --

    def test_name(self) -> None:
        self.assertEqual(self.tool.name, "github_list_repos")

    def test_is_not_mutating(self) -> None:
        self.assertFalse(self.tool.is_mutating)

    def test_required_params_empty(self) -> None:
        self.assertEqual(self.tool.input_schema["required"], [])

    # -- execute: own repos (no owner) --

    @patch("micro_x_agent_loop.tools.github.github_list_repos_tool.get_github_client")
    def test_execute_own_repos(self, mock_get_client: AsyncMock) -> None:
        repos = [_sample_repo(), _sample_repo(full_name="owner/other", private=True)]

        client = AsyncMock()
        client.get.return_value = _make_response(200, repos)
        mock_get_client.return_value = client

        result = asyncio.run(
            self.tool.execute({})
        )

        self.assertIn("Repos for you: 2 result(s)", result)
        self.assertIn("owner/my-repo [public]", result)
        self.assertIn("owner/other [private]", result)

        call_args = client.get.call_args
        self.assertEqual(call_args.args[0], "/user/repos")

    # -- execute: specific owner --

    @patch("micro_x_agent_loop.tools.github.github_list_repos_tool.get_github_client")
    def test_execute_specific_owner(self, mock_get_client: AsyncMock) -> None:
        repos = [_sample_repo(full_name="someuser/proj")]

        client = AsyncMock()
        client.get.return_value = _make_response(200, repos)
        mock_get_client.return_value = client

        result = asyncio.run(
            self.tool.execute({"owner": "someuser"})
        )

        self.assertIn("Repos for someuser: 1 result(s)", result)
        call_args = client.get.call_args
        self.assertEqual(call_args.args[0], "/users/someuser/repos")

    # -- execute: empty result --

    @patch("micro_x_agent_loop.tools.github.github_list_repos_tool.get_github_client")
    def test_execute_empty(self, mock_get_client: AsyncMock) -> None:
        client = AsyncMock()
        client.get.return_value = _make_response(200, [])
        mock_get_client.return_value = client

        result = asyncio.run(
            self.tool.execute({"owner": "nobody"})
        )

        self.assertIn("No repositories found", result)

    # -- execute: formatting details --

    @patch("micro_x_agent_loop.tools.github.github_list_repos_tool.get_github_client")
    def test_format_includes_language_stars_date(self, mock_get_client: AsyncMock) -> None:
        repos = [_sample_repo(language="Rust", stars=100, updated="2026-01-15T00:00:00Z")]

        client = AsyncMock()
        client.get.return_value = _make_response(200, repos)
        mock_get_client.return_value = client

        result = asyncio.run(
            self.tool.execute({})
        )

        self.assertIn("Rust", result)
        self.assertIn("stars: 100", result)
        self.assertIn("updated: 2026-01-15", result)

    @patch("micro_x_agent_loop.tools.github.github_list_repos_tool.get_github_client")
    def test_format_no_language(self, mock_get_client: AsyncMock) -> None:
        repos = [_sample_repo(language="")]  # empty string → falsy

        client = AsyncMock()
        client.get.return_value = _make_response(200, repos)
        mock_get_client.return_value = client

        result = asyncio.run(
            self.tool.execute({})
        )

        # Language should be omitted, line should start with stars
        self.assertIn("stars: 42", result)

    @patch("micro_x_agent_loop.tools.github.github_list_repos_tool.get_github_client")
    def test_long_description_truncated(self, mock_get_client: AsyncMock) -> None:
        repos = [_sample_repo(description="A" * 200)]

        client = AsyncMock()
        client.get.return_value = _make_response(200, repos)
        mock_get_client.return_value = client

        result = asyncio.run(
            self.tool.execute({})
        )

        self.assertIn("...", result)

    # -- execute: maxResults capped --

    @patch("micro_x_agent_loop.tools.github.github_list_repos_tool.get_github_client")
    def test_max_results_capped(self, mock_get_client: AsyncMock) -> None:
        client = AsyncMock()
        client.get.return_value = _make_response(200, [])
        mock_get_client.return_value = client

        asyncio.run(
            self.tool.execute({"maxResults": 100})
        )

        call_kwargs = client.get.call_args
        self.assertEqual(call_kwargs.kwargs["params"]["per_page"], 30)

    # -- execute: params forwarding --

    @patch("micro_x_agent_loop.tools.github.github_list_repos_tool.get_github_client")
    def test_params_forwarded(self, mock_get_client: AsyncMock) -> None:
        client = AsyncMock()
        client.get.return_value = _make_response(200, [])
        mock_get_client.return_value = client

        asyncio.run(
            self.tool.execute({"type": "public", "sort": "created"})
        )

        call_kwargs = client.get.call_args
        params = call_kwargs.kwargs["params"]
        self.assertEqual(params["type"], "public")
        self.assertEqual(params["sort"], "created")

    # -- execute: API error --

    @patch("micro_x_agent_loop.tools.github.github_list_repos_tool.get_github_client")
    def test_execute_api_error(self, mock_get_client: AsyncMock) -> None:
        client = AsyncMock()
        client.get.return_value = _make_response(401, {"message": "Bad credentials"})
        mock_get_client.return_value = client

        result = asyncio.run(
            self.tool.execute({})
        )

        self.assertIn("GitHub API error: HTTP 401", result)

    # -- execute: exception --

    @patch("micro_x_agent_loop.tools.github.github_list_repos_tool.get_github_client")
    def test_execute_exception(self, mock_get_client: AsyncMock) -> None:
        mock_get_client.side_effect = RuntimeError("timeout")

        result = asyncio.run(
            self.tool.execute({})
        )

        self.assertIn("Error listing repos:", result)
        self.assertIn("timeout", result)

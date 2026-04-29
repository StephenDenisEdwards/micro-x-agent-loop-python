"""Integration tests for GitHub template wrappers (tools/template-py/tools.py).

Tests the full stack: Python wrapper -> McpClient -> MCP server -> GitHub API.
Verifies that structuredContent propagates correctly and wrappers return
typed data (list[dict], dict) with the expected keys.

Requires GITHUB_TOKEN in .env or environment.
Run:  pytest tests/integration/test_github_wrappers.py -v
"""

import importlib.util
from pathlib import Path

import pytest

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "tools" / "template-py"


def _load_module(name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(name, file_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_tools = _load_module("_test_template_tools", TEMPLATE_DIR / "tools.py")

github_list_repos = _tools.github_list_repos
github_get_file = _tools.github_get_file
github_search_code = _tools.github_search_code
github_list_prs = _tools.github_list_prs
github_get_pr = _tools.github_get_pr
github_create_pr = _tools.github_create_pr
github_list_issues = _tools.github_list_issues
github_create_issue = _tools.github_create_issue

# Public repo for read-only tests
TEST_OWNER = "octocat"
TEST_REPO = "octocat/Hello-World"

# All tests share a single event loop and MCP server session
pytestmark = pytest.mark.asyncio(loop_scope="session")


# ---------------------------------------------------------------------------
# github_list_repos
# ---------------------------------------------------------------------------


class TestListRepos:
    async def test_returns_list(self, clients):
        repos = await github_list_repos(clients, owner=TEST_OWNER, max_results=3)
        assert isinstance(repos, list)
        assert len(repos) > 0

    async def test_repo_has_expected_keys(self, clients):
        repos = await github_list_repos(clients, owner=TEST_OWNER, max_results=1)
        repo = repos[0]
        expected = {"name", "full_name", "description", "url", "language", "stars", "forks", "visibility", "updated"}
        assert expected.issubset(repo.keys()), f"Missing: {expected - repo.keys()}"

    async def test_value_types(self, clients):
        repos = await github_list_repos(clients, owner=TEST_OWNER, max_results=1)
        repo = repos[0]
        assert isinstance(repo["name"], str) and repo["name"]
        assert isinstance(repo["full_name"], str) and "/" in repo["full_name"]
        assert isinstance(repo["stars"], (int, float))
        assert repo["visibility"] in ("public", "private")

    async def test_max_results_respected(self, clients):
        repos = await github_list_repos(clients, owner=TEST_OWNER, max_results=2)
        assert len(repos) <= 2


# ---------------------------------------------------------------------------
# github_get_file
# ---------------------------------------------------------------------------


class TestGetFile:
    async def test_file_returns_dict_with_content(self, clients):
        result = await github_get_file(clients, repo=TEST_REPO, path="README")
        assert isinstance(result, dict)
        assert result["type"] == "file"
        assert isinstance(result["content"], str)
        assert len(result["content"]) > 0

    async def test_file_has_repo_and_path(self, clients):
        result = await github_get_file(clients, repo=TEST_REPO, path="README")
        assert result["repo"] == TEST_REPO
        assert result["path"] == "README"

    async def test_directory_returns_entries(self, clients):
        # "/" passes Zod min(1) check, gets stripped to "" = root dir
        result = await github_get_file(clients, repo=TEST_REPO, path="/")
        assert isinstance(result, dict)
        assert result["type"] == "directory"
        assert isinstance(result["entries"], list)
        assert len(result["entries"]) > 0

    async def test_directory_entry_has_name_and_type(self, clients):
        result = await github_get_file(clients, repo=TEST_REPO, path="/")
        entry = result["entries"][0]
        assert "name" in entry
        assert "type" in entry


# ---------------------------------------------------------------------------
# github_search_code
# ---------------------------------------------------------------------------


class TestSearchCode:
    async def test_returns_list(self, clients):
        results = await github_search_code(
            clients,
            query="Hello",
            repo=TEST_REPO,
            max_results=3,
        )
        assert isinstance(results, list)

    async def test_result_has_expected_keys(self, clients):
        results = await github_search_code(
            clients,
            query="Hello",
            repo=TEST_REPO,
            max_results=1,
        )
        if not results:
            pytest.skip("Search returned 0 results")
        expected = {"repo", "path", "url", "fragment"}
        assert expected.issubset(results[0].keys())

    async def test_repo_field_matches(self, clients):
        results = await github_search_code(
            clients,
            query="Hello",
            repo=TEST_REPO,
            max_results=1,
        )
        if not results:
            pytest.skip("Search returned 0 results")
        assert results[0]["repo"] == TEST_REPO


# ---------------------------------------------------------------------------
# github_list_prs
# ---------------------------------------------------------------------------


class TestListPrs:
    async def test_returns_list(self, clients):
        prs = await github_list_prs(clients, repo=TEST_REPO, state="all", max_results=3)
        assert isinstance(prs, list)

    async def test_pr_has_expected_keys(self, clients):
        prs = await github_list_prs(clients, repo=TEST_REPO, state="all", max_results=1)
        if not prs:
            pytest.skip("No PRs in test repo")
        expected = {"number", "title", "author", "state", "updated", "url"}
        assert expected.issubset(prs[0].keys()), f"Missing: {expected - prs[0].keys()}"

    async def test_number_is_int(self, clients):
        prs = await github_list_prs(clients, repo=TEST_REPO, state="all", max_results=1)
        if not prs:
            pytest.skip("No PRs in test repo")
        assert isinstance(prs[0]["number"], int)


# ---------------------------------------------------------------------------
# github_get_pr
# ---------------------------------------------------------------------------


class TestGetPr:
    async def test_returns_dict_with_details(self, clients):
        # First find a real PR number
        prs = await github_list_prs(clients, repo=TEST_REPO, state="all", max_results=1)
        if not prs:
            pytest.skip("No PRs in test repo")
        pr_number = prs[0]["number"]

        result = await github_get_pr(clients, repo=TEST_REPO, number=pr_number)
        assert isinstance(result, dict)
        expected = {"number", "title", "state", "author", "url", "head", "base"}
        assert expected.issubset(result.keys()), f"Missing: {expected - result.keys()}"

    async def test_has_diff_stats(self, clients):
        prs = await github_list_prs(clients, repo=TEST_REPO, state="all", max_results=1)
        if not prs:
            pytest.skip("No PRs in test repo")

        result = await github_get_pr(clients, repo=TEST_REPO, number=prs[0]["number"])
        for key in ("additions", "deletions", "changed_files"):
            assert key in result, f"Missing diff stat: {key}"
            assert isinstance(result[key], (int, float))


# ---------------------------------------------------------------------------
# github_list_issues
# ---------------------------------------------------------------------------


class TestListIssues:
    async def test_returns_list(self, clients):
        issues = await github_list_issues(
            clients,
            repo=TEST_REPO,
            state="all",
            max_results=3,
        )
        assert isinstance(issues, list)

    async def test_issue_has_expected_keys(self, clients):
        issues = await github_list_issues(
            clients,
            repo=TEST_REPO,
            state="all",
            max_results=1,
        )
        if not issues:
            pytest.skip("No issues in test repo")
        expected = {"number", "title", "author", "state", "created", "comments", "labels", "url"}
        assert expected.issubset(issues[0].keys()), f"Missing: {expected - issues[0].keys()}"

    async def test_labels_is_list(self, clients):
        issues = await github_list_issues(
            clients,
            repo=TEST_REPO,
            state="all",
            max_results=1,
        )
        if not issues:
            pytest.skip("No issues in test repo")
        assert isinstance(issues[0]["labels"], list)


# ---------------------------------------------------------------------------
# github_create_pr / github_create_issue — mutating, skip by default
# ---------------------------------------------------------------------------


class TestCreatePr:
    @pytest.mark.skip(reason="Mutating — creates a real PR")
    async def test_placeholder(self, clients):
        pass


class TestCreateIssue:
    @pytest.mark.skip(reason="Mutating — creates a real issue")
    async def test_placeholder(self, clients):
        pass

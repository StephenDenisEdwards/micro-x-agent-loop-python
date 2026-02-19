from typing import Any

from loguru import logger

from micro_x_agent_loop.tools.github.github_auth import get_github_client


class GitHubSearchCodeTool:
    def __init__(self, token: str):
        self._token = token

    @property
    def name(self) -> str:
        return "github_search_code"

    @property
    def description(self) -> str:
        return (
            "Search for code across GitHub repositories. "
            "Returns matching files with context snippets. "
            "Note: limited to 10 requests/minute."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (code keywords, symbols, etc.)",
                },
                "repo": {
                    "type": "string",
                    "description": "Limit search to a repository in owner/repo format",
                },
                "language": {
                    "type": "string",
                    "description": "Filter by programming language (e.g. python, javascript)",
                },
                "maxResults": {
                    "type": "number",
                    "description": "Max results to return (default 10, max 20)",
                },
            },
            "required": ["query"],
        }

    @property
    def is_mutating(self) -> bool:
        return False

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        return []

    async def execute(self, tool_input: dict[str, Any]) -> str:
        try:
            client = await get_github_client(self._token)
            query = tool_input["query"]
            repo = tool_input.get("repo")
            language = tool_input.get("language")
            max_results = min(int(tool_input.get("maxResults", 10)), 20)

            q_parts = [query]
            if repo:
                q_parts.append(f"repo:{repo}")
            if language:
                q_parts.append(f"language:{language}")

            resp = await client.get(
                "/search/code",
                params={"q": " ".join(q_parts), "per_page": max_results},
                headers={"Accept": "application/vnd.github.text-match+json"},
            )
            if resp.status_code != 200:
                return f"GitHub API error: HTTP {resp.status_code} -- {resp.text}"

            data = resp.json()
            items = data.get("items", [])
            total = data.get("total_count", len(items))

            return self._format_results(items, total)
        except Exception as ex:
            logger.error(f"github_search_code failed: {ex}")
            return f"Error searching code: {ex}"

    def _format_results(self, items: list[dict], total: int) -> str:
        if not items:
            return "Code search: 0 results"

        lines = [f"Code search: {len(items)} of {total} result(s)", ""]
        for i, item in enumerate(items, 1):
            repo_name = item.get("repository", {}).get("full_name", "?")
            path = item.get("path", "?")
            lines.append(f"{i}. {repo_name} -- {path}")

            text_matches = item.get("text_matches", [])
            if text_matches:
                fragment = text_matches[0].get("fragment", "").strip()
                # Show first match fragment, truncated
                if len(fragment) > 200:
                    fragment = fragment[:200] + "..."
                for frag_line in fragment.splitlines()[:4]:
                    lines.append(f"   {frag_line}")
            lines.append("")

        return "\n".join(lines).rstrip()

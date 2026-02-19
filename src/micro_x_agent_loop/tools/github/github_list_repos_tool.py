from typing import Any

from loguru import logger

from micro_x_agent_loop.tools.github.github_auth import get_github_client


class GitHubListReposTool:
    def __init__(self, token: str):
        self._token = token

    @property
    def name(self) -> str:
        return "github_list_repos"

    @property
    def description(self) -> str:
        return (
            "List GitHub repositories for the authenticated user or a specific owner. "
            "If owner is omitted, lists your own repositories."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "Username or organization. If omitted, lists your repos.",
                },
                "type": {
                    "type": "string",
                    "enum": ["all", "owner", "public", "private", "member"],
                    "description": "Filter by type (default: all). 'owner'/'private'/'member' only work for your own repos.",
                },
                "sort": {
                    "type": "string",
                    "enum": ["created", "updated", "pushed", "full_name"],
                    "description": "Sort field (default: updated)",
                },
                "maxResults": {
                    "type": "number",
                    "description": "Max results to return (default 10, max 30)",
                },
            },
            "required": [],
        }

    @property
    def is_mutating(self) -> bool:
        return False

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        return []

    async def execute(self, tool_input: dict[str, Any]) -> str:
        try:
            client = await get_github_client(self._token)
            owner = tool_input.get("owner")
            repo_type = tool_input.get("type", "all")
            sort = tool_input.get("sort", "updated")
            max_results = min(int(tool_input.get("maxResults", 10)), 30)

            params: dict[str, Any] = {
                "per_page": max_results,
                "sort": sort,
                "direction": "desc",
            }

            if owner:
                url = f"/users/{owner}/repos"
                params["type"] = repo_type
            else:
                url = "/user/repos"
                params["type"] = repo_type

            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return f"GitHub API error: HTTP {resp.status_code} -- {resp.text}"

            repos = resp.json()
            who = owner or "you"
            header = f"Repos for {who}: {len(repos)} result(s)"
            return self._format_repos(header, repos)
        except Exception as ex:
            logger.error(f"github_list_repos failed: {ex}")
            return f"Error listing repos: {ex}"

    def _format_repos(self, header: str, repos: list[dict]) -> str:
        if not repos:
            return f"{header}\n\nNo repositories found."
        lines = [header, ""]
        for i, repo in enumerate(repos, 1):
            name = repo.get("full_name", "?")
            desc = repo.get("description") or ""
            if len(desc) > 100:
                desc = desc[:100] + "..."
            private = repo.get("private", False)
            visibility = "private" if private else "public"
            language = repo.get("language") or ""
            stars = repo.get("stargazers_count", 0)
            updated = repo.get("updated_at", "")[:10]

            lines.append(f"{i}. {name} [{visibility}]")
            if desc:
                lines.append(f"   {desc}")
            detail_parts = []
            if language:
                detail_parts.append(language)
            detail_parts.append(f"stars: {stars}")
            detail_parts.append(f"updated: {updated}")
            lines.append(f"   {' | '.join(detail_parts)}")
            lines.append("")
        return "\n".join(lines).rstrip()

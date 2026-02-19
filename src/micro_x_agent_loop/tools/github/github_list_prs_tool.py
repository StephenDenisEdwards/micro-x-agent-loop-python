from typing import Any

from loguru import logger

from micro_x_agent_loop.tools.github.github_auth import get_github_client


class GitHubListPRsTool:
    def __init__(self, token: str):
        self._token = token

    @property
    def name(self) -> str:
        return "github_list_prs"

    @property
    def description(self) -> str:
        return (
            "List pull requests for a GitHub repository. "
            "If repo is omitted, lists PRs authored by you across all repos."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/repo format. If omitted, lists your PRs across all repos.",
                },
                "state": {
                    "type": "string",
                    "enum": ["open", "closed", "all"],
                    "description": "Filter by state (default: open)",
                },
                "author": {
                    "type": "string",
                    "description": "Filter by author username",
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
            repo = tool_input.get("repo")
            state = tool_input.get("state", "open")
            author = tool_input.get("author")
            max_results = min(int(tool_input.get("maxResults", 10)), 30)

            if repo:
                params: dict[str, Any] = {
                    "state": state,
                    "per_page": max_results,
                }
                if author:
                    # Repo endpoint doesn't have author filter — use search instead
                    return await self._search_prs(client, state, author, max_results, repo)
                resp = await client.get(f"/repos/{repo}/pulls", params=params)
                if resp.status_code != 200:
                    return f"GitHub API error: HTTP {resp.status_code} -- {resp.text}"
                prs = resp.json()
                header = f"PRs ({state}) for {repo}: {len(prs)} result(s)"
            else:
                return await self._search_prs(client, state, author, max_results)

            return self._format_prs(header, prs)
        except Exception as ex:
            logger.error(f"github_list_prs failed: {ex}")
            return f"Error listing PRs: {ex}"

    async def _search_prs(
        self,
        client: Any,
        state: str,
        author: str | None,
        max_results: int,
        repo: str | None = None,
    ) -> str:
        q_parts = ["type:pr"]
        if repo:
            q_parts.append(f"repo:{repo}")
        if author:
            q_parts.append(f"author:{author}")
        else:
            q_parts.append("author:@me")
        if state in ("open", "closed"):
            q_parts.append(f"state:{state}")

        resp = await client.get(
            "/search/issues",
            params={"q": " ".join(q_parts), "per_page": max_results, "sort": "updated"},
        )
        if resp.status_code != 200:
            return f"GitHub API error: HTTP {resp.status_code} -- {resp.text}"
        data = resp.json()
        items = data.get("items", [])
        total = data.get("total_count", len(items))
        header = f"PRs ({state}): {len(items)} of {total} result(s)"
        # Search API returns issues-shaped objects; normalize to PR-like dicts
        prs = []
        for item in items:
            prs.append({
                "number": item["number"],
                "title": item["title"],
                "user": item.get("user", {}),
                "head": {"label": item.get("pull_request", {}).get("url", "").split("/")[-1] if item.get("pull_request") else "?"},
                "base": {"ref": "?"},
                "updated_at": item.get("updated_at", ""),
                "html_url": item.get("html_url", ""),
                "_from_search": True,
            })
        return self._format_prs(header, prs)

    def _format_prs(self, header: str, prs: list[dict]) -> str:
        if not prs:
            return f"{header}\n\nNo pull requests found."
        lines = [header, ""]
        for i, pr in enumerate(prs, 1):
            number = pr["number"]
            title = pr["title"]
            author = pr.get("user", {}).get("login", "unknown")
            updated = pr.get("updated_at", "")[:10]
            if pr.get("_from_search"):
                branch_info = ""
            else:
                head_ref = pr.get("head", {}).get("ref", "?")
                base_ref = pr.get("base", {}).get("ref", "?")
                branch_info = f" | Branch: {head_ref} -> {base_ref}"
            url = pr.get("html_url", "")
            lines.append(f"{i}. #{number} — {title}")
            lines.append(f"   Author: {author}{branch_info} | Updated: {updated}")
            if url:
                lines.append(f"   {url}")
            lines.append("")
        return "\n".join(lines).rstrip()

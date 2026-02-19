from typing import Any

from loguru import logger

from micro_x_agent_loop.tools.github.github_auth import get_github_client


class GitHubListIssuesTool:
    def __init__(self, token: str):
        self._token = token

    @property
    def name(self) -> str:
        return "github_list_issues"

    @property
    def description(self) -> str:
        return (
            "List or search issues in a GitHub repository. "
            "If repo is omitted or a query is provided, uses GitHub search."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/repo format. If omitted, searches across your repos.",
                },
                "state": {
                    "type": "string",
                    "enum": ["open", "closed", "all"],
                    "description": "Filter by state (default: open)",
                },
                "labels": {
                    "type": "string",
                    "description": "Comma-separated label names to filter by",
                },
                "query": {
                    "type": "string",
                    "description": "Search query (GitHub search syntax). When provided, uses search API.",
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
            labels = tool_input.get("labels")
            query = tool_input.get("query")
            max_results = min(int(tool_input.get("maxResults", 10)), 30)

            if query or not repo:
                return await self._search_issues(client, repo, state, labels, query, max_results)

            # Direct repo listing (filters out PRs)
            params: dict[str, Any] = {
                "state": state,
                "per_page": max_results,
            }
            if labels:
                params["labels"] = labels

            resp = await client.get(f"/repos/{repo}/issues", params=params)
            if resp.status_code != 200:
                return f"GitHub API error: HTTP {resp.status_code} -- {resp.text}"

            # The issues endpoint also returns PRs; filter them out
            issues = [i for i in resp.json() if "pull_request" not in i]
            header = f"Issues ({state}) for {repo}: {len(issues)} result(s)"
            return self._format_issues(header, issues)
        except Exception as ex:
            logger.error(f"github_list_issues failed: {ex}")
            return f"Error listing issues: {ex}"

    async def _search_issues(
        self,
        client: Any,
        repo: str | None,
        state: str,
        labels: str | None,
        query: str | None,
        max_results: int,
    ) -> str:
        q_parts = ["type:issue"]
        if repo:
            q_parts.append(f"repo:{repo}")
        if state in ("open", "closed"):
            q_parts.append(f"state:{state}")
        if labels:
            for label in labels.split(","):
                label = label.strip()
                if label:
                    q_parts.append(f'label:"{label}"')
        if query:
            q_parts.append(query)

        resp = await client.get(
            "/search/issues",
            params={"q": " ".join(q_parts), "per_page": max_results, "sort": "updated"},
        )
        if resp.status_code != 200:
            return f"GitHub API error: HTTP {resp.status_code} -- {resp.text}"

        data = resp.json()
        items = data.get("items", [])
        total = data.get("total_count", len(items))
        header = f"Issues ({state}): {len(items)} of {total} result(s)"
        return self._format_issues(header, items)

    def _format_issues(self, header: str, issues: list[dict]) -> str:
        if not issues:
            return f"{header}\n\nNo issues found."
        lines = [header, ""]
        for i, issue in enumerate(issues, 1):
            number = issue["number"]
            title = issue["title"]
            author = issue.get("user", {}).get("login", "unknown")
            created = issue.get("created_at", "")[:10]
            comments = issue.get("comments", 0)
            label_names = [l["name"] for l in issue.get("labels", [])]
            label_str = f" [{', '.join(label_names)}]" if label_names else ""
            url = issue.get("html_url", "")

            lines.append(f"{i}. #{number} — {title}{label_str}")
            lines.append(f"   Author: {author} | Created: {created} | Comments: {comments}")
            if url:
                lines.append(f"   {url}")
            lines.append("")
        return "\n".join(lines).rstrip()

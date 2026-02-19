from typing import Any

from loguru import logger

from micro_x_agent_loop.tools.github.github_auth import get_github_client


class GitHubCreateIssueTool:
    def __init__(self, token: str):
        self._token = token

    @property
    def name(self) -> str:
        return "github_create_issue"

    @property
    def description(self) -> str:
        return "Create a new issue in a GitHub repository."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/repo format",
                },
                "title": {
                    "type": "string",
                    "description": "Issue title",
                },
                "body": {
                    "type": "string",
                    "description": "Issue body (markdown)",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Label names to apply",
                },
                "assignees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Usernames to assign",
                },
            },
            "required": ["repo", "title"],
        }

    @property
    def is_mutating(self) -> bool:
        return True

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        return []

    async def execute(self, tool_input: dict[str, Any]) -> str:
        try:
            client = await get_github_client(self._token)
            repo = tool_input["repo"]

            payload: dict[str, Any] = {"title": tool_input["title"]}
            if "body" in tool_input:
                payload["body"] = tool_input["body"]
            if "labels" in tool_input:
                payload["labels"] = tool_input["labels"]
            if "assignees" in tool_input:
                payload["assignees"] = tool_input["assignees"]

            resp = await client.post(f"/repos/{repo}/issues", json=payload)
            if resp.status_code not in (200, 201):
                return f"GitHub API error: HTTP {resp.status_code} -- {resp.text}"

            issue = resp.json()
            number = issue["number"]
            title = issue["title"]
            url = issue["html_url"]
            return f"Issue created: #{number} — {title}\n{url}"
        except Exception as ex:
            logger.error(f"github_create_issue failed: {ex}")
            return f"Error creating issue: {ex}"

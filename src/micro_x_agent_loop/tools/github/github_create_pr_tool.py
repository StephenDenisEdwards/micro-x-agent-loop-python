from typing import Any

from loguru import logger

from micro_x_agent_loop.tools.github.github_auth import get_github_client


class GitHubCreatePRTool:
    def __init__(self, token: str):
        self._token = token

    @property
    def name(self) -> str:
        return "github_create_pr"

    @property
    def description(self) -> str:
        return "Create a pull request in a GitHub repository."

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
                    "description": "PR title",
                },
                "head": {
                    "type": "string",
                    "description": "Branch containing changes",
                },
                "body": {
                    "type": "string",
                    "description": "PR description (markdown)",
                },
                "base": {
                    "type": "string",
                    "description": "Branch to merge into (default: main)",
                },
                "draft": {
                    "type": "boolean",
                    "description": "Create as draft PR (default: false)",
                },
            },
            "required": ["repo", "title", "head"],
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

            payload: dict[str, Any] = {
                "title": tool_input["title"],
                "head": tool_input["head"],
                "base": tool_input.get("base", "main"),
            }
            if "body" in tool_input:
                payload["body"] = tool_input["body"]
            if "draft" in tool_input:
                payload["draft"] = tool_input["draft"]

            resp = await client.post(f"/repos/{repo}/pulls", json=payload)
            if resp.status_code not in (200, 201):
                return f"GitHub API error: HTTP {resp.status_code} -- {resp.text}"

            pr = resp.json()
            number = pr["number"]
            title = pr["title"]
            head_ref = pr.get("head", {}).get("ref", "?")
            base_ref = pr.get("base", {}).get("ref", "?")
            draft = pr.get("draft", False)
            url = pr["html_url"]
            draft_str = " (draft)" if draft else ""

            return (
                f"PR created: #{number} — {title}{draft_str}\n"
                f"Branch: {head_ref} -> {base_ref}\n"
                f"{url}"
            )
        except Exception as ex:
            logger.error(f"github_create_pr failed: {ex}")
            return f"Error creating PR: {ex}"

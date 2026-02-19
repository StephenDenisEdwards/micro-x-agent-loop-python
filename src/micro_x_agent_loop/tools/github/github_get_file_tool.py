import base64
from typing import Any

from loguru import logger

from micro_x_agent_loop.tools.github.github_auth import get_github_client

_MAX_CONTENT_CHARS = 100_000


class GitHubGetFileTool:
    def __init__(self, token: str):
        self._token = token

    @property
    def name(self) -> str:
        return "github_get_file"

    @property
    def description(self) -> str:
        return (
            "Get a file or directory listing from a GitHub repository. "
            "Returns decoded file content or a directory listing."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/repo format",
                },
                "path": {
                    "type": "string",
                    "description": "Path to file or directory within the repository",
                },
                "ref": {
                    "type": "string",
                    "description": "Branch, tag, or commit SHA (default: repo default branch)",
                },
            },
            "required": ["repo", "path"],
        }

    @property
    def is_mutating(self) -> bool:
        return False

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        return []

    async def execute(self, tool_input: dict[str, Any]) -> str:
        try:
            client = await get_github_client(self._token)
            repo = tool_input["repo"]
            path = tool_input["path"].strip("/")
            ref = tool_input.get("ref")

            params: dict[str, str] = {}
            if ref:
                params["ref"] = ref

            resp = await client.get(f"/repos/{repo}/contents/{path}", params=params)
            if resp.status_code != 200:
                return f"GitHub API error: HTTP {resp.status_code} -- {resp.text}"

            data = resp.json()

            if isinstance(data, list):
                return self._format_directory(repo, path, ref, data)

            if data.get("type") == "dir":
                return self._format_directory(repo, path, ref, data)

            return self._format_file(repo, path, ref, data)
        except Exception as ex:
            logger.error(f"github_get_file failed: {ex}")
            return f"Error getting file: {ex}"

    def _format_file(self, repo: str, path: str, ref: str | None, data: dict) -> str:
        size = data.get("size", 0)
        size_str = self._human_size(size)
        ref_str = f" (ref: {ref})" if ref else ""

        content_b64 = data.get("content", "")
        try:
            content = base64.b64decode(content_b64).decode("utf-8", errors="replace")
        except Exception:
            return f"File: {repo}/{path}{ref_str} ({size_str}) -- binary or undecodable content"

        if len(content) > _MAX_CONTENT_CHARS:
            content = content[:_MAX_CONTENT_CHARS] + f"\n\n... truncated ({size_str} total)"

        return f"File: {repo}/{path}{ref_str} ({size_str})\n\n{content}"

    def _format_directory(
        self, repo: str, path: str, ref: str | None, items: list[dict]
    ) -> str:
        ref_str = f" (ref: {ref})" if ref else ""
        lines = [f"Directory: {repo}/{path}{ref_str} -- {len(items)} entries", ""]
        for item in items:
            name = item.get("name", "?")
            item_type = item.get("type", "?")
            size = item.get("size", 0)
            if item_type == "dir":
                lines.append(f"  {name}/")
            else:
                lines.append(f"  {name}  ({self._human_size(size)})")
        return "\n".join(lines)

    @staticmethod
    def _human_size(nbytes: int) -> str:
        if nbytes < 1024:
            return f"{nbytes} B"
        elif nbytes < 1024 * 1024:
            return f"{nbytes / 1024:.1f} KB"
        else:
            return f"{nbytes / (1024 * 1024):.1f} MB"

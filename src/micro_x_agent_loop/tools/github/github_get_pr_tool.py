from typing import Any

from loguru import logger

from micro_x_agent_loop.tools.github.github_auth import get_github_client


class GitHubGetPRTool:
    def __init__(self, token: str):
        self._token = token

    @property
    def name(self) -> str:
        return "github_get_pr"

    @property
    def description(self) -> str:
        return (
            "Get detailed information about a specific pull request, "
            "including diff stats, reviews, and CI status."
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
                "number": {
                    "type": "number",
                    "description": "Pull request number",
                },
            },
            "required": ["repo", "number"],
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
            number = int(tool_input["number"])

            # Fetch PR details, reviews, and check runs in parallel-ish (sequential for simplicity)
            pr_resp = await client.get(f"/repos/{repo}/pulls/{number}")
            if pr_resp.status_code != 200:
                return f"GitHub API error: HTTP {pr_resp.status_code} -- {pr_resp.text}"
            pr = pr_resp.json()

            reviews_resp = await client.get(f"/repos/{repo}/pulls/{number}/reviews")
            reviews = reviews_resp.json() if reviews_resp.status_code == 200 else []

            head_sha = pr.get("head", {}).get("sha", "")
            checks_resp = await client.get(f"/repos/{repo}/commits/{head_sha}/check-runs")
            check_runs = checks_resp.json().get("check_runs", []) if checks_resp.status_code == 200 else []

            return self._format_pr(pr, reviews, check_runs)
        except Exception as ex:
            logger.error(f"github_get_pr failed: {ex}")
            return f"Error getting PR: {ex}"

    def _format_pr(self, pr: dict, reviews: list, check_runs: list) -> str:
        title = pr["title"]
        number = pr["number"]
        state = pr["state"]
        author = pr.get("user", {}).get("login", "unknown")
        head_ref = pr.get("head", {}).get("ref", "?")
        base_ref = pr.get("base", {}).get("ref", "?")
        created = pr.get("created_at", "")[:10]
        updated = pr.get("updated_at", "")[:10]
        mergeable = pr.get("mergeable")
        additions = pr.get("additions", 0)
        deletions = pr.get("deletions", 0)
        changed_files = pr.get("changed_files", 0)
        url = pr.get("html_url", "")
        draft = pr.get("draft", False)

        body = pr.get("body") or ""
        if len(body) > 1000:
            body = body[:1000] + "..."

        # Summarize reviews
        approved = 0
        changes_requested = 0
        for r in reviews:
            s = r.get("state", "")
            if s == "APPROVED":
                approved += 1
            elif s == "CHANGES_REQUESTED":
                changes_requested += 1

        # Summarize CI
        if not check_runs:
            ci_status = "no checks"
        else:
            conclusions = [cr.get("conclusion") for cr in check_runs]
            if all(c == "success" for c in conclusions):
                ci_status = "passing"
            elif any(c == "failure" for c in conclusions):
                ci_status = "failing"
            elif any(c is None for c in conclusions):
                ci_status = "in progress"
            else:
                ci_status = ", ".join(set(str(c) for c in conclusions))

        mergeable_str = {True: "yes", False: "no", None: "unknown"}.get(mergeable, "unknown")
        draft_str = " (draft)" if draft else ""

        lines = [
            f"#{number} — {title}{draft_str}",
            f"State: {state} | Mergeable: {mergeable_str}",
            f"Author: {author} | Branch: {head_ref} -> {base_ref}",
            f"Created: {created} | Updated: {updated}",
            f"Reviews: {approved} approved, {changes_requested} changes requested",
            f"CI: {ci_status}",
            f"Diff: +{additions} -{deletions} in {changed_files} file(s)",
            f"URL: {url}",
        ]
        if body:
            lines.append("")
            lines.append(body)

        return "\n".join(lines)

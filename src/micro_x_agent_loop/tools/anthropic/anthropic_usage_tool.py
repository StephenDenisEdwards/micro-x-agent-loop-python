import json
from typing import Any

import httpx

_BASE_URL = "https://api.anthropic.com/v1/organizations"

_ENDPOINTS = {
    "usage": "/usage_report/messages",
    "cost": "/cost_report",
    "claude_code": "/usage_report/claude_code",
}

_REPORT_LABELS = {
    "usage": "Token Usage Report",
    "cost": "Cost Report",
    "claude_code": "Claude Code Usage Report",
}


def _convert_cost_amounts(data: dict) -> None:
    """Convert 'amount' fields from cents to dollars in-place, recursively.

    The Anthropic cost API returns amounts in lowest currency units (cents).
    E.g. "123.45" in USD means $1.23. We divide by 100 and rename to 'amount_usd'.
    """
    for key in list(data.keys()):
        if key == "amount" and "currency" in data:
            cents = float(data.pop(key))
            data["amount_usd"] = round(cents / 100, 2)
        elif isinstance(data[key], dict):
            _convert_cost_amounts(data[key])
        elif isinstance(data[key], list):
            for item in data[key]:
                if isinstance(item, dict):
                    _convert_cost_amounts(item)


class AnthropicUsageTool:
    def __init__(self, admin_api_key: str) -> None:
        self._admin_key = admin_api_key

    @property
    def name(self) -> str:
        return "anthropic_usage"

    @property
    def description(self) -> str:
        return (
            "Query Anthropic Admin API for organization usage and cost reports. "
            "Supports three actions: 'usage' (token-level usage), 'cost' (spend in USD, converted from cents), "
            "'claude_code' (Claude Code productivity metrics)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["usage", "cost", "claude_code"],
                    "description": "Which report: 'usage' (token usage), 'cost' (spend in USD), 'claude_code' (productivity metrics)",
                },
                "starting_at": {
                    "type": "string",
                    "description": "Start time — RFC 3339 for usage/cost (e.g. '2025-02-01T00:00:00Z'), YYYY-MM-DD for claude_code",
                },
                "ending_at": {
                    "type": "string",
                    "description": "Optional end time (same format as starting_at)",
                },
                "bucket_width": {
                    "type": "string",
                    "description": "Time granularity: '1m', '1h', or '1d' (usage supports all three; cost only supports '1d')",
                },
                "group_by": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Group results by fields (e.g. ['model', 'workspace_id'] for usage; ['workspace_id', 'description'] for cost)",
                },
                "limit": {
                    "type": "number",
                    "description": "Max number of time buckets / records to return",
                },
            },
            "required": ["action", "starting_at"],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        try:
            action = tool_input["action"]
            if action not in _ENDPOINTS:
                return f"Unknown action '{action}'. Must be one of: usage, cost, claude_code."

            url = _BASE_URL + _ENDPOINTS[action]

            params: list[tuple[str, str]] = [
                ("starting_at", tool_input["starting_at"]),
            ]

            if ending_at := tool_input.get("ending_at"):
                params.append(("ending_at", ending_at))

            if bucket_width := tool_input.get("bucket_width"):
                params.append(("bucket_width", bucket_width))

            if group_by := tool_input.get("group_by"):
                for field in group_by:
                    params.append(("group_by[]", field))

            if limit := tool_input.get("limit"):
                params.append(("limit", str(int(limit))))

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={
                        "x-api-key": self._admin_key,
                        "anthropic-version": "2023-06-01",
                    },
                    params=params,
                )

            if response.status_code != 200:
                return f"Anthropic Admin API error: HTTP {response.status_code} — {response.text}"

            data = response.json()
            label = _REPORT_LABELS[action]

            if action == "cost":
                _convert_cost_amounts(data)

            return f"{label}:\n{json.dumps(data, indent=2)}"

        except Exception as ex:
            return f"Error querying Anthropic Admin API: {ex}"

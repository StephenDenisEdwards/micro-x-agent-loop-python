from __future__ import annotations

import json
from typing import Any


class ToolResultFormatter:
    """Formats ToolResult.structured into text for the LLM context window.

    Uses per-tool format config from the ``ToolFormatting`` config section.
    Falls back to ``DefaultFormat`` (json) when no per-tool config exists,
    and to ``ToolResult.text`` when no ``structuredContent`` is present.
    """

    def __init__(
        self,
        tool_formatting: dict[str, dict[str, Any]] | None = None,
        default_format: dict[str, Any] | None = None,
    ) -> None:
        self._tool_formatting = tool_formatting or {}
        self._default_format = default_format or {"format": "json"}

    def get_tool_format(self, tool_name: str) -> dict | None:
        return self._tool_formatting.get(tool_name)

    @property
    def default_format(self) -> dict:
        return self._default_format

    def format(
        self,
        tool_name: str,
        text: str,
        structured: dict[str, Any] | None,
    ) -> str:
        """Format a tool result for the LLM context window.

        Args:
            tool_name: The full tool name (e.g. ``filesystem__bash``).
            text: The TextContent fallback from the MCP response.
            structured: The structuredContent from the MCP response, or None.

        Returns:
            Formatted text string for the LLM.
        """
        if structured is None:
            return text

        fmt_config = self._tool_formatting.get(tool_name, self._default_format)
        strategy = fmt_config.get("format", "json")

        if strategy == "text":
            return self._format_text(structured, fmt_config)
        if strategy == "table":
            return self._format_table(structured, fmt_config)
        if strategy == "key_value":
            return self._format_key_value(structured)
        # Default: json
        return self._format_json(structured)

    @staticmethod
    def _format_json(structured: dict[str, Any]) -> str:
        return json.dumps(structured, indent=2, ensure_ascii=False, default=str)

    @staticmethod
    def _format_text(structured: dict[str, Any], config: dict[str, Any]) -> str:
        field = config.get("field")
        if field and field in structured:
            value = structured[field]
            return str(value) if not isinstance(value, str) else value
        # No field specified or field not found — try single-string heuristic:
        # if the structured result has exactly one string value, return it.
        string_values = [v for v in structured.values() if isinstance(v, str)]
        if len(string_values) == 1:
            return string_values[0]
        return json.dumps(structured, indent=2, ensure_ascii=False, default=str)

    @staticmethod
    def _format_table(structured: dict[str, Any] | list[Any], config: dict[str, Any]) -> str:
        max_rows = int(config.get("max_rows", 50))

        # Find the array to tabulate. Look for a top-level list value,
        # or treat the whole structured result as a single-item list.
        rows: list[dict[str, Any]] = []
        if isinstance(structured, list):
            rows = structured
        else:
            for v in structured.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    rows = v
                    break
            if not rows:
                # No array found — fall back to key_value
                return ToolResultFormatter._format_key_value(structured)

        if not rows:
            return "(empty)"

        rows = rows[:max_rows]

        # Collect all column keys in insertion order
        columns: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    columns.append(key)
                    seen.add(key)

        # Build markdown table
        col_widths = [len(c) for c in columns]
        for row in rows:
            for i, col in enumerate(columns):
                cell = str(row.get(col, ""))
                col_widths[i] = max(col_widths[i], len(cell))

        header = "| " + " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(columns)) + " |"
        separator = "|-" + "-|-".join("-" * w for w in col_widths) + "-|"
        lines = [header, separator]
        for row in rows:
            cells = [str(row.get(col, "")).ljust(col_widths[i]) for i, col in enumerate(columns)]
            lines.append("| " + " | ".join(cells) + " |")

        result = "\n".join(lines)
        total = (
            len(structured)
            if isinstance(structured, list)
            else sum(len(v) for v in structured.values() if isinstance(v, list))
        )
        if total > max_rows:
            result += f"\n\n[Showing {max_rows} of {total} rows]"
        return result

    @staticmethod
    def _format_key_value(structured: dict[str, Any]) -> str:
        lines: list[str] = []
        for key, value in structured.items():
            if isinstance(value, (dict, list)):
                value_str = json.dumps(value, ensure_ascii=False, default=str)
            else:
                value_str = str(value)
            lines.append(f"{key}: {value_str}")
        return "\n".join(lines)

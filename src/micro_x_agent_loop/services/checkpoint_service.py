from __future__ import annotations


class CheckpointService:
    def __init__(self, *, line_prefix: str, short_id_len: int = 8):
        self._line_prefix = line_prefix
        self._short_id_len = short_id_len

    def _short_id(self, value: str) -> str:
        if len(value) <= self._short_id_len:
            return value
        return value[: self._short_id_len]

    def format_checkpoint_list_entry(self, checkpoint: dict) -> str:
        tools = checkpoint.get("tools", [])
        tool_text = ", ".join(tools) if tools else "n/a"
        preview = checkpoint.get("user_preview", "")
        preview_text = f', prompt="{preview}"' if preview else ""
        short_id = self._short_id(checkpoint["id"])
        return (
            f"{self._line_prefix}- [{short_id}] (id={checkpoint['id']}, created={checkpoint['created_at']}, "
            f"tools={tool_text}{preview_text})"
        )

    def format_rewind_outcome_lines(self, checkpoint_id: str, outcomes: list[dict[str, str]]) -> list[str]:
        lines = [f"{self._line_prefix}Rewind {checkpoint_id} results:"]
        for outcome in outcomes:
            detail = outcome["detail"]
            suffix = f" ({detail})" if detail else ""
            lines.append(f"{self._line_prefix}- {outcome['path']}: {outcome['status']}{suffix}")
        return lines

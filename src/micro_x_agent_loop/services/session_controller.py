from __future__ import annotations


class SessionController:
    def __init__(self, *, line_prefix: str, short_id_len: int = 8):
        self._line_prefix = line_prefix
        self._short_id_len = short_id_len

    def short_id(self, value: str) -> str:
        if len(value) <= self._short_id_len:
            return value
        return value[: self._short_id_len]

    def format_session_list_entry(self, session: dict, *, active_session_id: str | None) -> str:
        marker = "*" if session["id"] == active_session_id else " "
        parent = session["parent_session_id"] or "-"
        title = session.get("title", session["id"])
        short_id = self.short_id(session["id"])
        return (
            f"{self._line_prefix}{marker} {title} [{short_id}] (id={session['id']}) "
            f"(status={session['status']}, created={session['created_at']}, "
            f"updated={session['updated_at']}, parent={parent})"
        )

    def format_resumed_summary_lines(self, summary: dict) -> list[str]:
        lines = [f"{self._line_prefix}Session summary:"]
        lines.append(
            f"{self._line_prefix}- Created: {summary['created_at']} | "
            f"Updated: {summary['updated_at']}"
        )
        lines.append(
            f"{self._line_prefix}- Messages: {summary['message_count']} "
            f"(user={summary['user_message_count']}, assistant={summary['assistant_message_count']})"
        )
        lines.append(f"{self._line_prefix}- Checkpoints: {summary['checkpoint_count']}")
        last_user = summary.get("last_user_preview", "")
        if last_user:
            lines.append(f"{self._line_prefix}- Last user: {last_user}")
        last_assistant = summary.get("last_assistant_preview", "")
        if last_assistant:
            lines.append(f"{self._line_prefix}- Last assistant: {last_assistant}")
        return lines

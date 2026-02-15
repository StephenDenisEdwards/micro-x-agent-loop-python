from typing import Any

from micro_x_agent_loop.tools.gmail.gmail_auth import get_gmail_service
from micro_x_agent_loop.tools.gmail.gmail_parser import get_header, extract_text


class GmailReadTool:
    def __init__(self, google_client_id: str, google_client_secret: str):
        self._google_client_id = google_client_id
        self._google_client_secret = google_client_secret

    @property
    def name(self) -> str:
        return "gmail_read"

    @property
    def description(self) -> str:
        return "Read the full content of a Gmail email by its message ID (from gmail_search results)."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "messageId": {
                    "type": "string",
                    "description": "The Gmail message ID (from gmail_search results)",
                },
            },
            "required": ["messageId"],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        try:
            gmail = await get_gmail_service(self._google_client_id, self._google_client_secret)
            message_id = tool_input["messageId"]

            message = (
                gmail.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )

            headers = message.get("payload", {}).get("headers", [])
            from_addr = get_header(headers, "From")
            to_addr = get_header(headers, "To")
            subject = get_header(headers, "Subject")
            date = get_header(headers, "Date")

            payload = message.get("payload")
            body = extract_text(payload) if payload else "(no text content)"

            if not body:
                body = "(no text content)"

            return f"From: {from_addr}\nTo: {to_addr}\nDate: {date}\nSubject: {subject}\n\n{body}"

        except Exception as ex:
            return f"Error reading email: {ex}"

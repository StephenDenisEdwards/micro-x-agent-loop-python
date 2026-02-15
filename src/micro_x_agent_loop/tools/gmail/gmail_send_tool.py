import base64
from typing import Any

from micro_x_agent_loop.tools.gmail.gmail_auth import get_gmail_service


class GmailSendTool:
    def __init__(self, google_client_id: str, google_client_secret: str):
        self._google_client_id = google_client_id
        self._google_client_secret = google_client_secret

    @property
    def name(self) -> str:
        return "gmail_send"

    @property
    def description(self) -> str:
        return "Send an email from your Gmail account."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "body": {
                    "type": "string",
                    "description": "Email body (plain text)",
                },
            },
            "required": ["to", "subject", "body"],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        try:
            gmail = await get_gmail_service(self._google_client_id, self._google_client_secret)
            to = tool_input["to"]
            subject = tool_input["subject"]
            body = tool_input["body"]

            message_text = (
                f"To: {to}\r\n"
                f"Subject: {subject}\r\n"
                f"Content-Type: text/plain; charset=utf-8\r\n"
                f"\r\n"
                f"{body}"
            )

            raw = base64.urlsafe_b64encode(message_text.encode("utf-8")).decode("ascii").rstrip("=")

            result = (
                gmail.users()
                .messages()
                .send(userId="me", body={"raw": raw})
                .execute()
            )

            return f"Email sent successfully (ID: {result['id']})"

        except Exception as ex:
            return f"Error sending email: {ex}"

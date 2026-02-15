from typing import Any

from micro_x_agent_loop.tools.gmail.gmail_auth import get_gmail_service
from micro_x_agent_loop.tools.gmail.gmail_parser import get_header


class GmailSearchTool:
    def __init__(self, google_client_id: str, google_client_secret: str):
        self._google_client_id = google_client_id
        self._google_client_secret = google_client_secret

    @property
    def name(self) -> str:
        return "gmail_search"

    @property
    def description(self) -> str:
        return (
            "Search Gmail using Gmail search syntax (e.g. 'is:unread', "
            "'from:someone@example.com', 'subject:hello'). Returns a list of matching "
            "emails with ID, date, from, subject, and snippet."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail search query (e.g. 'is:unread', 'from:boss@co.com newer_than:7d')",
                },
                "maxResults": {
                    "type": "number",
                    "description": "Max number of results (default 10)",
                },
            },
            "required": ["query"],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        try:
            gmail = await get_gmail_service(self._google_client_id, self._google_client_secret)
            query = tool_input["query"]
            max_results = int(tool_input.get("maxResults", 10))

            list_response = (
                gmail.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )

            messages = list_response.get("messages", [])
            if not messages:
                return "No emails found matching your query."

            results = []
            for msg in messages:
                detail = (
                    gmail.users()
                    .messages()
                    .get(userId="me", id=msg["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"])
                    .execute()
                )

                headers = detail.get("payload", {}).get("headers", [])
                from_addr = get_header(headers, "From")
                subject = get_header(headers, "Subject")
                date = get_header(headers, "Date")
                snippet = detail.get("snippet", "")

                results.append(
                    f"ID: {msg['id']}\n"
                    f"  Date: {date}\n"
                    f"  From: {from_addr}\n"
                    f"  Subject: {subject}\n"
                    f"  Snippet: {snippet}"
                )

            return "\n\n".join(results)

        except Exception as ex:
            return f"Error searching Gmail: {ex}"

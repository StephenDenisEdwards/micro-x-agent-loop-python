from typing import Any

from loguru import logger

from micro_x_agent_loop.tools.contacts.contacts_auth import get_contacts_service
from micro_x_agent_loop.tools.contacts.contacts_formatter import format_contact_summary


class ContactsListTool:
    def __init__(self, google_client_id: str, google_client_secret: str):
        self._google_client_id = google_client_id
        self._google_client_secret = google_client_secret

    @property
    def name(self) -> str:
        return "contacts_list"

    @property
    def description(self) -> str:
        return (
            "List Google Contacts. Returns contacts with name, email, and phone number. "
            "Supports pagination via pageToken."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pageSize": {
                    "type": "number",
                    "description": "Number of contacts to return (default 10, max 100).",
                },
                "pageToken": {
                    "type": "string",
                    "description": "Page token from a previous response for pagination.",
                },
                "sortOrder": {
                    "type": "string",
                    "description": "Sort order: 'LAST_MODIFIED_ASCENDING', 'LAST_MODIFIED_DESCENDING', 'FIRST_NAME_ASCENDING', or 'LAST_NAME_ASCENDING'.",
                },
            },
            "required": [],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        try:
            service = await get_contacts_service(self._google_client_id, self._google_client_secret)
            page_size = min(int(tool_input.get("pageSize", 10)), 100)
            page_token = tool_input.get("pageToken")
            sort_order = tool_input.get("sortOrder")

            kwargs: dict[str, Any] = {
                "resourceName": "people/me",
                "personFields": "names,emailAddresses,phoneNumbers",
                "pageSize": page_size,
            }
            if page_token:
                kwargs["pageToken"] = page_token
            if sort_order:
                kwargs["sortOrder"] = sort_order

            response = service.people().connections().list(**kwargs).execute()
            connections = response.get("connections", [])

            if not connections:
                return "No contacts found."

            formatted = []
            for person in connections:
                formatted.append(format_contact_summary(person))

            result = "\n\n".join(formatted)

            next_page_token = response.get("nextPageToken")
            if next_page_token:
                result += f"\n\n--- More results available. Use pageToken: {next_page_token} ---"

            return result

        except Exception as ex:
            logger.error(f"contacts_list error: {ex}")
            return f"Error listing contacts: {ex}"

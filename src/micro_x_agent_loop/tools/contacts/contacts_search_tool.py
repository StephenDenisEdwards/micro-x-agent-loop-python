from typing import Any

from loguru import logger

from micro_x_agent_loop.tools.contacts.contacts_auth import get_contacts_service
from micro_x_agent_loop.tools.contacts.contacts_formatter import format_contact_summary


class ContactsSearchTool:
    def __init__(self, google_client_id: str, google_client_secret: str):
        self._google_client_id = google_client_id
        self._google_client_secret = google_client_secret

    @property
    def name(self) -> str:
        return "contacts_search"

    @property
    def description(self) -> str:
        return (
            "Search Google Contacts by name, email, phone number, or other fields. "
            "Returns matching contacts with name, email, and phone number."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (name, email, phone number, etc.).",
                },
                "pageSize": {
                    "type": "number",
                    "description": "Max number of results (default 10, max 30).",
                },
            },
            "required": ["query"],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        try:
            service = await get_contacts_service(self._google_client_id, self._google_client_secret)
            query = tool_input["query"]
            page_size = min(int(tool_input.get("pageSize", 10)), 30)

            response = (
                service.people()
                .searchContacts(
                    query=query,
                    readMask="names,emailAddresses,phoneNumbers",
                    pageSize=page_size,
                )
                .execute()
            )

            results = response.get("results", [])
            if not results:
                return "No contacts found matching your query."

            formatted = []
            for r in results:
                person = r.get("person", {})
                formatted.append(format_contact_summary(person))

            return "\n\n".join(formatted)

        except Exception as ex:
            logger.error(f"contacts_search error: {ex}")
            return f"Error searching contacts: {ex}"

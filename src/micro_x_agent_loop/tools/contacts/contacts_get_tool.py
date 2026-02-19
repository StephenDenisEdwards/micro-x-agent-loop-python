from typing import Any

from loguru import logger

from micro_x_agent_loop.tools.contacts.contacts_auth import get_contacts_service
from micro_x_agent_loop.tools.contacts.contacts_formatter import format_contact_detail


class ContactsGetTool:
    def __init__(self, google_client_id: str, google_client_secret: str):
        self._google_client_id = google_client_id
        self._google_client_secret = google_client_secret

    @property
    def name(self) -> str:
        return "contacts_get"

    @property
    def description(self) -> str:
        return (
            "Get full details of a Google Contact by resource name. "
            "Returns name, emails, phones, addresses, organization, biography, and etag "
            "(needed for updates)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "resourceName": {
                    "type": "string",
                    "description": "The contact's resource name (e.g. 'people/c1234567890').",
                },
            },
            "required": ["resourceName"],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        try:
            service = await get_contacts_service(self._google_client_id, self._google_client_secret)
            resource_name = tool_input["resourceName"]

            person = (
                service.people()
                .get(
                    resourceName=resource_name,
                    personFields="names,emailAddresses,phoneNumbers,addresses,organizations,biographies",
                )
                .execute()
            )

            return format_contact_detail(person)

        except Exception as ex:
            logger.error(f"contacts_get error: {ex}")
            return f"Error getting contact: {ex}"

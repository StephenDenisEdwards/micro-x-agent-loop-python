from typing import Any

from loguru import logger

from micro_x_agent_loop.tools.contacts.contacts_auth import get_contacts_service


class ContactsDeleteTool:
    def __init__(self, google_client_id: str, google_client_secret: str):
        self._google_client_id = google_client_id
        self._google_client_secret = google_client_secret

    @property
    def name(self) -> str:
        return "contacts_delete"

    @property
    def description(self) -> str:
        return "Delete a Google Contact by resource name. This action cannot be undone."

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

            service.people().deleteContact(resourceName=resource_name).execute()

            return f"Contact '{resource_name}' deleted successfully."

        except Exception as ex:
            logger.error(f"contacts_delete error: {ex}")
            return f"Error deleting contact: {ex}"

from typing import Any

from loguru import logger

from micro_x_agent_loop.tools.contacts.contacts_auth import get_contacts_service
from micro_x_agent_loop.tools.contacts.contacts_formatter import format_contact_detail


class ContactsCreateTool:
    def __init__(self, google_client_id: str, google_client_secret: str):
        self._google_client_id = google_client_id
        self._google_client_secret = google_client_secret

    @property
    def name(self) -> str:
        return "contacts_create"

    @property
    def description(self) -> str:
        return (
            "Create a new Google Contact. At minimum requires a given name. "
            "Can also set family name, email, phone, organization, and job title."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "givenName": {
                    "type": "string",
                    "description": "First/given name (required).",
                },
                "familyName": {
                    "type": "string",
                    "description": "Last/family name.",
                },
                "email": {
                    "type": "string",
                    "description": "Email address.",
                },
                "emailType": {
                    "type": "string",
                    "description": "Email type: 'home', 'work', or 'other' (default 'other').",
                },
                "phone": {
                    "type": "string",
                    "description": "Phone number.",
                },
                "phoneType": {
                    "type": "string",
                    "description": "Phone type: 'home', 'work', 'mobile', or 'other' (default 'other').",
                },
                "organization": {
                    "type": "string",
                    "description": "Company/organization name.",
                },
                "jobTitle": {
                    "type": "string",
                    "description": "Job title.",
                },
            },
            "required": ["givenName"],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        try:
            service = await get_contacts_service(self._google_client_id, self._google_client_secret)

            body: dict[str, Any] = {
                "names": [
                    {
                        "givenName": tool_input["givenName"],
                    }
                ],
            }

            family_name = tool_input.get("familyName")
            if family_name:
                body["names"][0]["familyName"] = family_name

            email = tool_input.get("email")
            if email:
                email_type = tool_input.get("emailType", "other")
                body["emailAddresses"] = [{"value": email, "type": email_type}]

            phone = tool_input.get("phone")
            if phone:
                phone_type = tool_input.get("phoneType", "other")
                body["phoneNumbers"] = [{"value": phone, "type": phone_type}]

            organization = tool_input.get("organization")
            job_title = tool_input.get("jobTitle")
            if organization or job_title:
                org: dict[str, str] = {}
                if organization:
                    org["name"] = organization
                if job_title:
                    org["title"] = job_title
                body["organizations"] = [org]

            person = service.people().createContact(body=body).execute()

            return "Contact created successfully.\n\n" + format_contact_detail(person)

        except Exception as ex:
            logger.error(f"contacts_create error: {ex}")
            return f"Error creating contact: {ex}"

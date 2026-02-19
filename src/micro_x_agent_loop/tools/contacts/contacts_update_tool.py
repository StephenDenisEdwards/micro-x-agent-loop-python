from typing import Any

from loguru import logger

from micro_x_agent_loop.tools.contacts.contacts_auth import get_contacts_service
from micro_x_agent_loop.tools.contacts.contacts_formatter import format_contact_detail


class ContactsUpdateTool:
    def __init__(self, google_client_id: str, google_client_secret: str):
        self._google_client_id = google_client_id
        self._google_client_secret = google_client_secret

    @property
    def name(self) -> str:
        return "contacts_update"

    @property
    def description(self) -> str:
        return (
            "Update an existing Google Contact. Requires the resource name and etag "
            "(from contacts_get). Provide only the fields you want to change."
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
                "etag": {
                    "type": "string",
                    "description": "The contact's etag (from contacts_get, required for concurrency control).",
                },
                "givenName": {
                    "type": "string",
                    "description": "New first/given name.",
                },
                "familyName": {
                    "type": "string",
                    "description": "New last/family name.",
                },
                "email": {
                    "type": "string",
                    "description": "New email address (replaces existing emails).",
                },
                "emailType": {
                    "type": "string",
                    "description": "Email type: 'home', 'work', or 'other' (default 'other').",
                },
                "phone": {
                    "type": "string",
                    "description": "New phone number (replaces existing phones).",
                },
                "phoneType": {
                    "type": "string",
                    "description": "Phone type: 'home', 'work', 'mobile', or 'other' (default 'other').",
                },
                "organization": {
                    "type": "string",
                    "description": "New company/organization name.",
                },
                "jobTitle": {
                    "type": "string",
                    "description": "New job title.",
                },
            },
            "required": ["resourceName", "etag"],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        try:
            service = await get_contacts_service(self._google_client_id, self._google_client_secret)
            resource_name = tool_input["resourceName"]

            body: dict[str, Any] = {
                "etag": tool_input["etag"],
            }

            update_fields = []

            given_name = tool_input.get("givenName")
            family_name = tool_input.get("familyName")
            if given_name or family_name:
                name_obj: dict[str, str] = {}
                if given_name:
                    name_obj["givenName"] = given_name
                if family_name:
                    name_obj["familyName"] = family_name
                body["names"] = [name_obj]
                update_fields.append("names")

            email = tool_input.get("email")
            if email:
                email_type = tool_input.get("emailType", "other")
                body["emailAddresses"] = [{"value": email, "type": email_type}]
                update_fields.append("emailAddresses")

            phone = tool_input.get("phone")
            if phone:
                phone_type = tool_input.get("phoneType", "other")
                body["phoneNumbers"] = [{"value": phone, "type": phone_type}]
                update_fields.append("phoneNumbers")

            organization = tool_input.get("organization")
            job_title = tool_input.get("jobTitle")
            if organization or job_title:
                org: dict[str, str] = {}
                if organization:
                    org["name"] = organization
                if job_title:
                    org["title"] = job_title
                body["organizations"] = [org]
                update_fields.append("organizations")

            if not update_fields:
                return "No fields to update. Provide at least one field to change."

            person = (
                service.people()
                .updateContact(
                    resourceName=resource_name,
                    body=body,
                    updatePersonFields=",".join(update_fields),
                )
                .execute()
            )

            return "Contact updated successfully.\n\n" + format_contact_detail(person)

        except Exception as ex:
            logger.error(f"contacts_update error: {ex}")
            return f"Error updating contact: {ex}"

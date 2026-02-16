import sys
from typing import Any

from micro_x_agent_loop.tools.calendar.calendar_auth import get_calendar_service


class CalendarCreateEventTool:
    def __init__(self, google_client_id: str, google_client_secret: str):
        self._google_client_id = google_client_id
        self._google_client_secret = google_client_secret

    @property
    def name(self) -> str:
        return "calendar_create_event"

    @property
    def description(self) -> str:
        return (
            "Create a Google Calendar event. Supports timed events (ISO 8601 with time) "
            "and all-day events (YYYY-MM-DD date only). Can add attendees by email."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Event title.",
                },
                "start": {
                    "type": "string",
                    "description": "Start time in ISO 8601 (e.g. '2025-06-15T14:00:00') or date only for all-day events (e.g. '2025-06-15').",
                },
                "end": {
                    "type": "string",
                    "description": "End time in ISO 8601 (e.g. '2025-06-15T15:00:00') or date only for all-day events (e.g. '2025-06-16').",
                },
                "description": {
                    "type": "string",
                    "description": "Event description/notes.",
                },
                "location": {
                    "type": "string",
                    "description": "Event location.",
                },
                "attendees": {
                    "type": "string",
                    "description": "Comma-separated email addresses of attendees.",
                },
                "calendarId": {
                    "type": "string",
                    "description": "Calendar ID (default 'primary').",
                },
            },
            "required": ["summary", "start", "end"],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        try:
            cal = await get_calendar_service(self._google_client_id, self._google_client_secret)

            summary = tool_input["summary"]
            start = tool_input["start"]
            end = tool_input["end"]
            description = tool_input.get("description", "")
            location = tool_input.get("location", "")
            attendees_str = tool_input.get("attendees", "")
            calendar_id = tool_input.get("calendarId", "primary")

            is_all_day = "T" not in start

            if is_all_day:
                start_body = {"date": start}
                end_body = {"date": end}
            else:
                start_body = {"dateTime": start}
                end_body = {"dateTime": end}

            event_body: dict[str, Any] = {
                "summary": summary,
                "start": start_body,
                "end": end_body,
            }

            if description:
                event_body["description"] = description
            if location:
                event_body["location"] = location
            if attendees_str:
                emails = [e.strip() for e in attendees_str.split(",") if e.strip()]
                event_body["attendees"] = [{"email": e} for e in emails]

            created = cal.events().insert(calendarId=calendar_id, body=event_body).execute()

            start_display = created.get("start", {}).get("dateTime") or created.get("start", {}).get("date", "")
            end_display = created.get("end", {}).get("dateTime") or created.get("end", {}).get("date", "")

            return (
                f"Event created successfully.\n"
                f"  ID: {created.get('id', '')}\n"
                f"  Summary: {created.get('summary', '')}\n"
                f"  Start: {start_display}\n"
                f"  End: {end_display}\n"
                f"  Link: {created.get('htmlLink', '')}"
            )

        except Exception as ex:
            print(f"  calendar_create_event error: {ex}", file=sys.stderr)
            return f"Error creating calendar event: {ex}"

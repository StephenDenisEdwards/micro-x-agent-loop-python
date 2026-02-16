import sys
from typing import Any

from micro_x_agent_loop.tools.calendar.calendar_auth import get_calendar_service


class CalendarGetEventTool:
    def __init__(self, google_client_id: str, google_client_secret: str):
        self._google_client_id = google_client_id
        self._google_client_secret = google_client_secret

    @property
    def name(self) -> str:
        return "calendar_get_event"

    @property
    def description(self) -> str:
        return "Get full details of a Google Calendar event by its event ID."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "eventId": {
                    "type": "string",
                    "description": "The event ID (from calendar_list_events results).",
                },
                "calendarId": {
                    "type": "string",
                    "description": "Calendar ID (default 'primary').",
                },
            },
            "required": ["eventId"],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        try:
            cal = await get_calendar_service(self._google_client_id, self._google_client_secret)
            event_id = tool_input["eventId"]
            calendar_id = tool_input.get("calendarId", "primary")

            event = cal.events().get(calendarId=calendar_id, eventId=event_id).execute()

            start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date", "")
            end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date", "")
            organizer = event.get("organizer", {})
            creator = event.get("creator", {})

            lines = [
                f"Summary: {event.get('summary', '(no title)')}",
                f"Status: {event.get('status', '')}",
                f"Start: {start}",
                f"End: {end}",
                f"Location: {event.get('location', '')}",
                f"Description: {event.get('description', '')}",
                f"Organizer: {organizer.get('email', '')}",
                f"Creator: {creator.get('email', '')}",
            ]

            attendees = event.get("attendees", [])
            if attendees:
                attendee_lines = []
                for a in attendees:
                    email = a.get("email", "")
                    status = a.get("responseStatus", "")
                    attendee_lines.append(f"    {email} ({status})")
                lines.append("Attendees:\n" + "\n".join(attendee_lines))

            conference = event.get("conferenceData", {})
            entry_points = conference.get("entryPoints", [])
            for ep in entry_points:
                if ep.get("entryPointType") == "video":
                    lines.append(f"Conference Link: {ep.get('uri', '')}")
                    break

            recurrence = event.get("recurrence", [])
            if recurrence:
                lines.append(f"Recurrence: {'; '.join(recurrence)}")

            return "\n".join(lines)

        except Exception as ex:
            print(f"  calendar_get_event error: {ex}", file=sys.stderr)
            return f"Error getting calendar event: {ex}"

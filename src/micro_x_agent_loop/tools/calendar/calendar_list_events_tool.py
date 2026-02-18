from datetime import datetime, timezone
from typing import Any

from loguru import logger

from micro_x_agent_loop.tools.calendar.calendar_auth import get_calendar_service


class CalendarListEventsTool:
    def __init__(self, google_client_id: str, google_client_secret: str):
        self._google_client_id = google_client_id
        self._google_client_secret = google_client_secret

    @property
    def name(self) -> str:
        return "calendar_list_events"

    @property
    def description(self) -> str:
        return (
            "List Google Calendar events by date range or search query. "
            "Returns event ID, summary, start/end times, location, status, and organizer. "
            "Defaults to today's events if no time range is specified."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "timeMin": {
                    "type": "string",
                    "description": "Start of time range in ISO 8601 format (e.g. '2025-06-01T00:00:00Z'). Defaults to start of today.",
                },
                "timeMax": {
                    "type": "string",
                    "description": "End of time range in ISO 8601 format (e.g. '2025-06-01T23:59:59Z'). Defaults to end of today.",
                },
                "query": {
                    "type": "string",
                    "description": "Free-text search query to filter events (searches summary, description, location, attendees).",
                },
                "maxResults": {
                    "type": "number",
                    "description": "Max number of results (default 10).",
                },
                "calendarId": {
                    "type": "string",
                    "description": "Calendar ID (default 'primary').",
                },
            },
            "required": [],
        }

    async def execute(self, tool_input: dict[str, Any]) -> str:
        try:
            cal = await get_calendar_service(self._google_client_id, self._google_client_secret)

            time_min = tool_input.get("timeMin")
            time_max = tool_input.get("timeMax")
            query = tool_input.get("query")
            max_results = int(tool_input.get("maxResults", 10))
            calendar_id = tool_input.get("calendarId", "primary")

            if not time_min and not time_max:
                now = datetime.now(timezone.utc)
                time_min = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
                time_max = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()

            kwargs: dict[str, Any] = {
                "calendarId": calendar_id,
                "maxResults": max_results,
                "singleEvents": True,
                "orderBy": "startTime",
            }
            if time_min:
                kwargs["timeMin"] = time_min
            if time_max:
                kwargs["timeMax"] = time_max
            if query:
                kwargs["q"] = query

            response = cal.events().list(**kwargs).execute()
            events = response.get("items", [])

            if not events:
                return "No events found."

            results = []
            for event in events:
                start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date", "")
                end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date", "")
                organizer = event.get("organizer", {}).get("email", "")

                results.append(
                    f"ID: {event.get('id', '')}\n"
                    f"  Summary: {event.get('summary', '(no title)')}\n"
                    f"  Start: {start}\n"
                    f"  End: {end}\n"
                    f"  Location: {event.get('location', '')}\n"
                    f"  Status: {event.get('status', '')}\n"
                    f"  Organizer: {organizer}"
                )

            return "\n\n".join(results)

        except Exception as ex:
            logger.error(f"calendar_list_events error: {ex}")
            return f"Error listing calendar events: {ex}"

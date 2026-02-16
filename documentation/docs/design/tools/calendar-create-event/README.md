# Tool: calendar_create_event

Create a Google Calendar event with optional attendees, location, and description.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `summary` | string | Yes | Event title. |
| `start` | string | Yes | Start time in ISO 8601 (e.g. `"2025-06-15T14:00:00"`) or date only for all-day events (e.g. `"2025-06-15"`). |
| `end` | string | Yes | End time in ISO 8601 (e.g. `"2025-06-15T15:00:00"`) or date only for all-day events (e.g. `"2025-06-16"`). |
| `description` | string | No | Event description/notes. |
| `location` | string | No | Event location. |
| `attendees` | string | No | Comma-separated email addresses of attendees. |
| `calendarId` | string | No | Calendar ID (default `"primary"`). |

## Behavior

- Creates an event using the Google Calendar API `events.insert` endpoint
- Detects all-day events vs timed events based on format: date-only (`YYYY-MM-DD`) uses `date`, ISO 8601 with `T` uses `dateTime`
- Returns the created event ID, summary, start/end times, and HTML link
- Attendees receive email invitations automatically
- **Conditional registration:** Only available when Google credentials are configured

## Implementation

- Source: `src/micro_x_agent_loop/tools/calendar/calendar_create_event_tool.py`
- Uses `google-api-python-client` for Calendar API access
- OAuth2 via `calendar_auth.get_calendar_service()`

## Example

```
you> Create a meeting tomorrow at 2pm with Alice and Bob
```

Claude calls:
```json
{
  "name": "calendar_create_event",
  "input": {
    "summary": "Meeting with Alice and Bob",
    "start": "2025-06-15T14:00:00",
    "end": "2025-06-15T15:00:00",
    "attendees": "alice@example.com, bob@example.com"
  }
}
```

```
you> Block off next Friday as an all-day event for the offsite
```

Claude calls:
```json
{
  "name": "calendar_create_event",
  "input": {
    "summary": "Team Offsite",
    "start": "2025-06-20",
    "end": "2025-06-21"
  }
}
```

## Authentication

Same OAuth2 flow as other Calendar tools. See [calendar_list_events](../calendar-list-events/README.md) for authentication details.

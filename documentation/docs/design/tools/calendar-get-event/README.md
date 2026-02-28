# Tool: calendar_get_event

Get full details of a Google Calendar event by its event ID.

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `eventId` | string | Yes | The event ID (from `calendar_list_events` results). |
| `calendarId` | string | No | Calendar ID (default `"primary"`). |

## Behavior

- Fetches the full event using the Google Calendar API `events.get` endpoint
- Returns: summary, status, start/end times, location, description, organizer, creator, attendees with response status, conference link, and recurrence rules
- **Availability:** Requires Google credentials in the `google` MCP server's `env` config

## Implementation

- Server: `mcp_servers/ts/packages/google/src/tools/calendar-get-event.ts`
- Uses `googleapis` for Calendar API access
- OAuth2 via unified Google auth module

## Example

```
you> Show me the details of that first meeting
```

Claude calls:
```json
{
  "name": "calendar_get_event",
  "input": {
    "eventId": "abc123def456"
  }
}
```

## Authentication

Same OAuth2 flow as other Calendar tools. See [calendar_list_events](../calendar-list-events/README.md) for authentication details.

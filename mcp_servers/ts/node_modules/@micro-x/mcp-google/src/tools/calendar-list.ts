import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { getCalendarService } from "../auth/google-auth.js";

export function registerCalendarList(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "calendar_list_events",
    {
      description:
        "List Google Calendar events by date range or search query. " +
        "Returns event ID, summary, start/end times, location, status, and organizer. " +
        "Defaults to today's events if no time range is specified.",
      inputSchema: {
        timeMin: z.string().optional().describe(
          "Start of time range in ISO 8601 format (e.g. '2025-06-01T00:00:00Z'). Defaults to start of today.",
        ),
        timeMax: z.string().optional().describe(
          "End of time range in ISO 8601 format (e.g. '2025-06-01T23:59:59Z'). Defaults to end of today.",
        ),
        query: z.string().optional().describe(
          "Free-text search query to filter events (searches summary, description, location, attendees).",
        ),
        maxResults: z.number().optional().describe("Max number of results (default 10)."),
        calendarId: z.string().optional().describe("Calendar ID (default 'primary')."),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "calendar_list_events", request_id: requestId }, "tool_call_start");

      try {
        const cal = await getCalendarService(clientId, clientSecret);

        let timeMin = input.timeMin;
        let timeMax = input.timeMax;
        const query = input.query;
        const maxResults = input.maxResults ?? 10;
        const calendarId = input.calendarId ?? "primary";

        // Default to today if no time range specified
        if (!timeMin && !timeMax) {
          const now = new Date();
          const startOfDay = new Date(now);
          startOfDay.setHours(0, 0, 0, 0);
          const endOfDay = new Date(now);
          endOfDay.setHours(23, 59, 59, 0);
          timeMin = startOfDay.toISOString();
          timeMax = endOfDay.toISOString();
        }

        const response = await cal.events.list({
          calendarId,
          maxResults,
          singleEvents: true,
          orderBy: "startTime",
          ...(timeMin ? { timeMin } : {}),
          ...(timeMax ? { timeMax } : {}),
          ...(query ? { q: query } : {}),
        });
        const events = response.data.items ?? [];

        if (events.length === 0) {
          const durationMs = Date.now() - startTime;
          logger.info(
            { tool: "calendar_list_events", request_id: requestId, duration_ms: durationMs, outcome: "success", count: 0 },
            "tool_call_end",
          );
          return {
            content: [{ type: "text" as const, text: "No events found." }],
          };
        }

        const results: string[] = [];
        for (const event of events) {
          const eventStart = event.start?.dateTime ?? event.start?.date ?? "";
          const eventEnd = event.end?.dateTime ?? event.end?.date ?? "";
          const organizer = event.organizer?.email ?? "";

          results.push(
            `ID: ${event.id ?? ""}\n` +
            `  Summary: ${event.summary ?? "(no title)"}\n` +
            `  Start: ${eventStart}\n` +
            `  End: ${eventEnd}\n` +
            `  Location: ${event.location ?? ""}\n` +
            `  Status: ${event.status ?? ""}\n` +
            `  Organizer: ${organizer}`,
          );
        }

        const text = results.join("\n\n");
        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "calendar_list_events", request_id: requestId, duration_ms: durationMs, outcome: "success", count: results.length },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "calendar_list_events", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error listing calendar events: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { getCalendarService } from "../auth/google-auth.js";

export function registerCalendarGet(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "calendar_get_event",
    {
      description: "Get full details of a Google Calendar event by its event ID.",
      inputSchema: {
        eventId: z.string().describe("The event ID (from calendar_list_events results)."),
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

      logger.info({ tool: "calendar_get_event", request_id: requestId }, "tool_call_start");

      try {
        const cal = await getCalendarService(clientId, clientSecret);
        const calendarId = input.calendarId ?? "primary";

        const response = await cal.events.get({
          calendarId,
          eventId: input.eventId,
        });

        const event = response.data;

        const eventStart = event.start?.dateTime ?? event.start?.date ?? "";
        const eventEnd = event.end?.dateTime ?? event.end?.date ?? "";
        const organizer = event.organizer ?? {};
        const creator = event.creator ?? {};

        const lines: string[] = [
          `Summary: ${event.summary ?? "(no title)"}`,
          `Status: ${event.status ?? ""}`,
          `Start: ${eventStart}`,
          `End: ${eventEnd}`,
          `Location: ${event.location ?? ""}`,
          `Description: ${event.description ?? ""}`,
          `Organizer: ${organizer.email ?? ""}`,
          `Creator: ${creator.email ?? ""}`,
        ];

        const attendees = event.attendees ?? [];
        if (attendees.length > 0) {
          const attendeeLines: string[] = [];
          for (const a of attendees) {
            const email = a.email ?? "";
            const status = a.responseStatus ?? "";
            attendeeLines.push(`    ${email} (${status})`);
          }
          lines.push("Attendees:\n" + attendeeLines.join("\n"));
        }

        const conference = event.conferenceData;
        const entryPoints = conference?.entryPoints ?? [];
        for (const ep of entryPoints) {
          if (ep.entryPointType === "video") {
            lines.push(`Conference Link: ${ep.uri ?? ""}`);
            break;
          }
        }

        const recurrence = event.recurrence ?? [];
        if (recurrence.length > 0) {
          lines.push(`Recurrence: ${recurrence.join("; ")}`);
        }

        const text = lines.join("\n");
        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "calendar_get_event", request_id: requestId, duration_ms: durationMs, outcome: "success" },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "calendar_get_event", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error getting calendar event: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

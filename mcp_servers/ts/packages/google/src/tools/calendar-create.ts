import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { getCalendarService } from "../auth/google-auth.js";

export function registerCalendarCreate(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "calendar_create_event",
    {
      description:
        "Create a Google Calendar event. Supports timed events (ISO 8601 with time) " +
        "and all-day events (YYYY-MM-DD date only). Can add attendees by email.",
      inputSchema: {
        summary: z.string().describe("Event title."),
        start: z.string().describe(
          "Start time in ISO 8601 (e.g. '2025-06-15T14:00:00') or date only for all-day events (e.g. '2025-06-15').",
        ),
        end: z.string().describe(
          "End time in ISO 8601 (e.g. '2025-06-15T15:00:00') or date only for all-day events (e.g. '2025-06-16').",
        ),
        description: z.string().optional().describe("Event description/notes."),
        location: z.string().optional().describe("Event location."),
        attendees: z.string().optional().describe("Comma-separated email addresses of attendees."),
        calendarId: z.string().optional().describe("Calendar ID (default 'primary')."),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "calendar_create_event", request_id: requestId }, "tool_call_start");

      try {
        const cal = await getCalendarService(clientId, clientSecret);

        const calendarId = input.calendarId ?? "primary";
        const isAllDay = !input.start.includes("T");

        const startBody = isAllDay
          ? { date: input.start }
          : { dateTime: input.start };
        const endBody = isAllDay
          ? { date: input.end }
          : { dateTime: input.end };

        const eventBody: Record<string, unknown> = {
          summary: input.summary,
          start: startBody,
          end: endBody,
        };

        if (input.description) {
          eventBody.description = input.description;
        }
        if (input.location) {
          eventBody.location = input.location;
        }
        if (input.attendees) {
          const emails = input.attendees
            .split(",")
            .map((e) => e.trim())
            .filter((e) => e.length > 0);
          eventBody.attendees = emails.map((email) => ({ email }));
        }

        const created = await cal.events.insert({
          calendarId,
          requestBody: eventBody,
        });

        const startDisplay =
          created.data.start?.dateTime ?? created.data.start?.date ?? "";
        const endDisplay =
          created.data.end?.dateTime ?? created.data.end?.date ?? "";

        const text =
          `Event created successfully.\n` +
          `  ID: ${created.data.id ?? ""}\n` +
          `  Summary: ${created.data.summary ?? ""}\n` +
          `  Start: ${startDisplay}\n` +
          `  End: ${endDisplay}\n` +
          `  Link: ${created.data.htmlLink ?? ""}`;

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "calendar_create_event", request_id: requestId, duration_ms: durationMs, outcome: "success" },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "calendar_create_event", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error creating calendar event: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

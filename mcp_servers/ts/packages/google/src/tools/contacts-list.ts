import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { getContactsService } from "../auth/google-auth.js";
import { formatContactSummary } from "./contacts-format.js";

export function registerContactsList(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "contacts_list",
    {
      description:
        "List Google Contacts. Returns contacts with name, email, and phone number. " +
        "Supports pagination via pageToken.",
      inputSchema: {
        pageSize: z.number().optional().describe("Number of contacts to return (default 10, max 100)."),
        pageToken: z.string().optional().describe("Page token from a previous response for pagination."),
        sortOrder: z.string().optional().describe(
          "Sort order: 'LAST_MODIFIED_ASCENDING', 'LAST_MODIFIED_DESCENDING', 'FIRST_NAME_ASCENDING', or 'LAST_NAME_ASCENDING'.",
        ),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "contacts_list", request_id: requestId }, "tool_call_start");

      try {
        const service = await getContactsService(clientId, clientSecret);
        const pageSize = Math.min(input.pageSize ?? 10, 100);

        const response = await service.people.connections.list({
          resourceName: "people/me",
          personFields: "names,emailAddresses,phoneNumbers",
          pageSize,
          ...(input.pageToken ? { pageToken: input.pageToken } : {}),
          ...(input.sortOrder ? { sortOrder: input.sortOrder } : {}),
        });
        const connections = response.data.connections ?? [];

        if (connections.length === 0) {
          const durationMs = Date.now() - startTime;
          logger.info(
            { tool: "contacts_list", request_id: requestId, duration_ms: durationMs, outcome: "success", count: 0 },
            "tool_call_end",
          );
          return {
            content: [{ type: "text" as const, text: "No contacts found." }],
          };
        }

        const formatted: string[] = [];
        for (const person of connections) {
          formatted.push(formatContactSummary(person));
        }

        let text = formatted.join("\n\n");

        const nextPageToken = response.data.nextPageToken;
        if (nextPageToken) {
          text += `\n\n--- More results available. Use pageToken: ${nextPageToken} ---`;
        }

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "contacts_list", request_id: requestId, duration_ms: durationMs, outcome: "success", count: connections.length },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "contacts_list", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error listing contacts: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

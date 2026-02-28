import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { getContactsService } from "../auth/google-auth.js";
import { formatContactSummary } from "./contacts-format.js";

export function registerContactsSearch(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "contacts_search",
    {
      description:
        "Search Google Contacts by name, email, phone number, or other fields. " +
        "Returns matching contacts with name, email, and phone number.",
      inputSchema: {
        query: z.string().describe("Search query (name, email, phone number, etc.)."),
        pageSize: z.number().optional().describe("Max number of results (default 10, max 30)."),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "contacts_search", request_id: requestId }, "tool_call_start");

      try {
        const service = await getContactsService(clientId, clientSecret);
        const pageSize = Math.min(input.pageSize ?? 10, 30);

        const response = await service.people.searchContacts({
          query: input.query,
          readMask: "names,emailAddresses,phoneNumbers",
          pageSize,
        });

        const results = response.data.results ?? [];
        if (results.length === 0) {
          const durationMs = Date.now() - startTime;
          logger.info(
            { tool: "contacts_search", request_id: requestId, duration_ms: durationMs, outcome: "success", count: 0 },
            "tool_call_end",
          );
          return {
            content: [{ type: "text" as const, text: "No contacts found matching your query." }],
          };
        }

        const formatted: string[] = [];
        for (const r of results) {
          const person = r.person ?? {};
          formatted.push(formatContactSummary(person));
        }

        const text = formatted.join("\n\n");
        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "contacts_search", request_id: requestId, duration_ms: durationMs, outcome: "success", count: results.length },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "contacts_search", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error searching contacts: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

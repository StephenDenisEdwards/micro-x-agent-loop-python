import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { getContactsService } from "../auth/google-auth.js";
import { formatContactDetail } from "./contacts-format.js";

export function registerContactsGet(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "contacts_get",
    {
      description:
        "Get full details of a Google Contact by resource name. " +
        "Returns name, emails, phones, addresses, organization, biography, and etag " +
        "(needed for updates).",
      inputSchema: {
        resourceName: z.string().describe("The contact's resource name (e.g. 'people/c1234567890')."),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "contacts_get", request_id: requestId }, "tool_call_start");

      try {
        const service = await getContactsService(clientId, clientSecret);

        const response = await service.people.get({
          resourceName: input.resourceName,
          personFields: "names,emailAddresses,phoneNumbers,addresses,organizations,biographies",
        });

        const text = formatContactDetail(response.data);

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "contacts_get", request_id: requestId, duration_ms: durationMs, outcome: "success" },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "contacts_get", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error getting contact: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

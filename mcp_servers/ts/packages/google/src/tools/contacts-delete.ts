import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { getContactsService } from "../auth/google-auth.js";

export function registerContactsDelete(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "contacts_delete",
    {
      description: "Delete a Google Contact by resource name. This action cannot be undone.",
      inputSchema: {
        resourceName: z.string().describe("The contact's resource name (e.g. 'people/c1234567890')."),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: true,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "contacts_delete", request_id: requestId }, "tool_call_start");

      try {
        const service = await getContactsService(clientId, clientSecret);

        await service.people.deleteContact({
          resourceName: input.resourceName,
        });

        const text = `Contact '${input.resourceName}' deleted successfully.`;

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "contacts_delete", request_id: requestId, duration_ms: durationMs, outcome: "success" },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "contacts_delete", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error deleting contact: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

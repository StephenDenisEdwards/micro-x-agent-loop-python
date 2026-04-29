import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { getContactsService } from "../auth/google-auth.js";
import { formatContactDetail } from "./contacts-format.js";

export function registerContactsCreate(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "contacts_create",
    {
      description:
        "Create a new Google Contact. At minimum requires a given name. " +
        "Can also set family name, email, phone, organization, and job title.",
      inputSchema: {
        givenName: z.string().describe("First/given name (required)."),
        familyName: z.string().optional().describe("Last/family name."),
        email: z.string().optional().describe("Email address."),
        emailType: z.string().optional().describe("Email type: 'home', 'work', or 'other' (default 'other')."),
        phone: z.string().optional().describe("Phone number."),
        phoneType: z.string().optional().describe("Phone type: 'home', 'work', 'mobile', or 'other' (default 'other')."),
        organization: z.string().optional().describe("Company/organization name."),
        jobTitle: z.string().optional().describe("Job title."),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "contacts_create", request_id: requestId }, "tool_call_start");

      try {
        const service = await getContactsService(clientId, clientSecret);

        const body: Record<string, unknown> = {
          names: [
            {
              givenName: input.givenName,
              ...(input.familyName ? { familyName: input.familyName } : {}),
            },
          ],
        };

        if (input.email) {
          const emailType = input.emailType ?? "other";
          body.emailAddresses = [{ value: input.email, type: emailType }];
        }

        if (input.phone) {
          const phoneType = input.phoneType ?? "other";
          body.phoneNumbers = [{ value: input.phone, type: phoneType }];
        }

        if (input.organization || input.jobTitle) {
          const org: Record<string, string> = {};
          if (input.organization) org.name = input.organization;
          if (input.jobTitle) org.title = input.jobTitle;
          body.organizations = [org];
        }

        const response = await service.people.createContact({
          requestBody: body,
        });

        const text = "Contact created successfully.\n\n" + formatContactDetail(response.data);

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "contacts_create", request_id: requestId, duration_ms: durationMs, outcome: "success" },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "contacts_create", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error creating contact: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

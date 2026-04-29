import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { getContactsService } from "../auth/google-auth.js";
import { formatContactDetail } from "./contacts-format.js";

export function registerContactsUpdate(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "contacts_update",
    {
      description:
        "Update an existing Google Contact. Requires the resource name and etag " +
        "(from contacts_get). Provide only the fields you want to change.",
      inputSchema: {
        resourceName: z.string().describe("The contact's resource name (e.g. 'people/c1234567890')."),
        etag: z.string().describe("The contact's etag (from contacts_get, required for concurrency control)."),
        givenName: z.string().optional().describe("New first/given name."),
        familyName: z.string().optional().describe("New last/family name."),
        email: z.string().optional().describe("New email address (replaces existing emails)."),
        emailType: z.string().optional().describe("Email type: 'home', 'work', or 'other' (default 'other')."),
        phone: z.string().optional().describe("New phone number (replaces existing phones)."),
        phoneType: z.string().optional().describe("Phone type: 'home', 'work', 'mobile', or 'other' (default 'other')."),
        organization: z.string().optional().describe("New company/organization name."),
        jobTitle: z.string().optional().describe("New job title."),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "contacts_update", request_id: requestId }, "tool_call_start");

      try {
        const service = await getContactsService(clientId, clientSecret);

        const body: Record<string, unknown> = {
          etag: input.etag,
        };

        const updateFields: string[] = [];

        if (input.givenName || input.familyName) {
          const nameObj: Record<string, string> = {};
          if (input.givenName) nameObj.givenName = input.givenName;
          if (input.familyName) nameObj.familyName = input.familyName;
          body.names = [nameObj];
          updateFields.push("names");
        }

        if (input.email) {
          const emailType = input.emailType ?? "other";
          body.emailAddresses = [{ value: input.email, type: emailType }];
          updateFields.push("emailAddresses");
        }

        if (input.phone) {
          const phoneType = input.phoneType ?? "other";
          body.phoneNumbers = [{ value: input.phone, type: phoneType }];
          updateFields.push("phoneNumbers");
        }

        if (input.organization || input.jobTitle) {
          const org: Record<string, string> = {};
          if (input.organization) org.name = input.organization;
          if (input.jobTitle) org.title = input.jobTitle;
          body.organizations = [org];
          updateFields.push("organizations");
        }

        if (updateFields.length === 0) {
          const durationMs = Date.now() - startTime;
          logger.info(
            { tool: "contacts_update", request_id: requestId, duration_ms: durationMs, outcome: "success" },
            "tool_call_end",
          );
          return {
            content: [{ type: "text" as const, text: "No fields to update. Provide at least one field to change." }],
          };
        }

        const response = await service.people.updateContact({
          resourceName: input.resourceName,
          updatePersonFields: updateFields.join(","),
          requestBody: body,
        });

        const text = "Contact updated successfully.\n\n" + formatContactDetail(response.data);

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "contacts_update", request_id: requestId, duration_ms: durationMs, outcome: "success" },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "contacts_update", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error updating contact: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

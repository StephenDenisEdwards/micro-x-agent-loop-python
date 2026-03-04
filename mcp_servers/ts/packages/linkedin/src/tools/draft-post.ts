import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { createDraft } from "../draft-store.js";
import type { LinkedInClient } from "../auth/linkedin-auth.js";
import { getLinkedInClient } from "../auth/linkedin-auth.js";

export function registerDraftPost(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "linkedin_draft_post",
    {
      description:
        "Create a draft LinkedIn text post for review before publishing. " +
        "Returns a draft_id that can be passed to linkedin_publish_draft to publish.",
      inputSchema: {
        text: z.string().min(1).max(3000).describe("Post text content (max 3000 characters)"),
        visibility: z
          .enum(["PUBLIC", "CONNECTIONS"])
          .default("PUBLIC")
          .describe("Post visibility")
          .optional(),
      },
      outputSchema: {
        draft_id: z.string(),
        preview: z.string(),
        visibility: z.string(),
        char_count: z.number().int(),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "linkedin_draft_post", request_id: requestId }, "tool_call_start");

      try {
        // Authenticate (triggers browser flow if needed, otherwise cached)
        const client: LinkedInClient = await getLinkedInClient(clientId, clientSecret);

        const visibility = input.visibility ?? "PUBLIC";

        // Build the LinkedIn API payload (not sent yet)
        const payload: Record<string, unknown> = {
          author: client.personUrn,
          commentary: input.text,
          visibility: visibility,
          distribution: {
            feedDistribution: "MAIN_FEED",
            targetEntities: [],
            thirdPartyDistributionChannels: [],
          },
          lifecycleState: "PUBLISHED",
          isReshareDisabledByAuthor: false,
        };

        // Truncate preview to first 200 chars
        const previewText = input.text.length > 200
          ? input.text.substring(0, 200) + "..."
          : input.text;

        const preview = `[LinkedIn Text Post — ${visibility}]\n\n${previewText}`;
        const draftId = createDraft("text", payload, preview);

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "linkedin_draft_post", request_id: requestId, duration_ms: durationMs, outcome: "success", draft_id: draftId },
          "tool_call_end",
        );

        const result = {
          draft_id: draftId,
          preview,
          visibility,
          char_count: input.text.length,
        };

        return {
          structuredContent: result,
          content: [
            {
              type: "text" as const,
              text: `Draft created (${draftId}).\n\n${preview}\n\nCharacters: ${input.text.length}/3000\nVisibility: ${visibility}\n\nUse linkedin_publish_draft with this draft_id to publish.`,
            },
          ],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "linkedin_draft_post", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error creating draft post: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

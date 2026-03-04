import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { createDraft } from "../draft-store.js";
import type { LinkedInClient } from "../auth/linkedin-auth.js";
import { getLinkedInClient } from "../auth/linkedin-auth.js";

export function registerDraftArticle(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "linkedin_draft_article",
    {
      description:
        "Create a draft LinkedIn article share (link post with preview card) for review before publishing. " +
        "Returns a draft_id that can be passed to linkedin_publish_draft to publish.",
      inputSchema: {
        url: z.string().url().describe("URL of the article to share"),
        title: z.string().min(1).max(200).describe("Article title for the share card"),
        description: z.string().min(1).max(500).describe("Article description for the share card"),
        commentary: z
          .string()
          .max(3000)
          .describe("Optional commentary text above the article card")
          .optional(),
        visibility: z
          .enum(["PUBLIC", "CONNECTIONS"])
          .default("PUBLIC")
          .describe("Post visibility")
          .optional(),
      },
      outputSchema: {
        draft_id: z.string(),
        preview: z.string(),
        url: z.string(),
        visibility: z.string(),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "linkedin_draft_article", request_id: requestId }, "tool_call_start");

      try {
        const client: LinkedInClient = await getLinkedInClient(clientId, clientSecret);

        const visibility = input.visibility ?? "PUBLIC";
        const commentary = input.commentary ?? "";

        // Build the LinkedIn API payload (not sent yet)
        const payload: Record<string, unknown> = {
          author: client.personUrn,
          commentary,
          visibility,
          distribution: {
            feedDistribution: "MAIN_FEED",
            targetEntities: [],
            thirdPartyDistributionChannels: [],
          },
          content: {
            article: {
              source: input.url,
              title: input.title,
              description: input.description,
            },
          },
          lifecycleState: "PUBLISHED",
          isReshareDisabledByAuthor: false,
        };

        const preview =
          `[LinkedIn Article Share — ${visibility}]\n\n` +
          (commentary ? `${commentary}\n\n` : "") +
          `📎 ${input.title}\n` +
          `   ${input.description}\n` +
          `   ${input.url}`;

        const draftId = createDraft("article", payload, preview);

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "linkedin_draft_article", request_id: requestId, duration_ms: durationMs, outcome: "success", draft_id: draftId },
          "tool_call_end",
        );

        const result = {
          draft_id: draftId,
          preview,
          url: input.url,
          visibility,
        };

        return {
          structuredContent: result,
          content: [
            {
              type: "text" as const,
              text: `Draft created (${draftId}).\n\n${preview}\n\nUse linkedin_publish_draft with this draft_id to publish.`,
            },
          ],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "linkedin_draft_article", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error creating draft article: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

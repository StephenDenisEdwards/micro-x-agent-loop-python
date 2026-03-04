import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x/mcp-shared";
import { getDraft, removeDraft } from "../draft-store.js";
import { getLinkedInClient } from "../auth/linkedin-auth.js";

const LINKEDIN_API_VERSION = "202601";

export function registerPublishDraft(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "linkedin_publish_draft",
    {
      description:
        "Publish a previously created LinkedIn draft. Requires a draft_id from " +
        "linkedin_draft_post or linkedin_draft_article. Drafts expire after 10 minutes.",
      inputSchema: {
        draft_id: z.string().uuid().describe("Draft ID returned by linkedin_draft_post or linkedin_draft_article"),
      },
      outputSchema: {
        post_urn: z.string(),
        post_url: z.string(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "linkedin_publish_draft", request_id: requestId, draft_id: input.draft_id }, "tool_call_start");

      try {
        const draft = getDraft(input.draft_id);
        if (!draft) {
          const durationMs = Date.now() - startTime;
          logger.warn(
            { tool: "linkedin_publish_draft", request_id: requestId, duration_ms: durationMs, outcome: "not_found", draft_id: input.draft_id },
            "tool_call_end",
          );
          return {
            content: [
              {
                type: "text" as const,
                text: "Draft not found or expired. Drafts expire after 10 minutes. Please create a new draft.",
              },
            ],
            isError: true,
          };
        }

        const client = await getLinkedInClient(clientId, clientSecret);

        const response = await resilientFetch(
          "https://api.linkedin.com/rest/posts",
          {
            method: "POST",
            headers: {
              "Authorization": `Bearer ${client.accessToken}`,
              "Content-Type": "application/json",
              "LinkedIn-Version": LINKEDIN_API_VERSION,
              "X-Restli-Protocol-Version": "2.0.0",
            },
            body: JSON.stringify(draft.payload),
          },
          { timeoutMs: 15_000, retries: 1 },
        );

        if (!response.ok) {
          const errorText = await response.text();
          throw new UpstreamError(
            `LinkedIn API error (${response.status}): ${errorText}`,
            response.status,
          );
        }

        // Post URN comes from x-restli-id header
        const postUrn = response.headers.get("x-restli-id") ?? "";
        // Construct the post URL from the URN
        // URN format: urn:li:share:{id} or urn:li:ugcPost:{id}
        const postId = postUrn.split(":").pop() ?? "";
        const postUrl = postId
          ? `https://www.linkedin.com/feed/update/${postUrn}/`
          : "";

        // Remove the published draft
        removeDraft(input.draft_id);

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "linkedin_publish_draft", request_id: requestId, duration_ms: durationMs, outcome: "success", post_urn: postUrn },
          "tool_call_end",
        );

        const result = {
          post_urn: postUrn,
          post_url: postUrl,
        };

        return {
          structuredContent: result,
          content: [
            {
              type: "text" as const,
              text: `Published successfully!\n\nPost URN: ${postUrn}\nURL: ${postUrl || "(URL will be available shortly)"}`,
            },
          ],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "linkedin_publish_draft", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error publishing draft: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

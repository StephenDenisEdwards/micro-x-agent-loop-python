import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { getXClient } from "../auth/x-auth.js";
import { uploadMedia } from "./upload-media.js";

export function registerUploadMedia(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "x_upload_media",
    {
      description:
        "Upload an image for use in a tweet. Returns a media_id. " +
        "Note: x_draft_tweet with media_paths handles upload automatically — " +
        "use this tool only for pre-uploading media. " +
        "Free tier limit: ~34 uploads per 24 hours. " +
        "Media IDs expire after ~24 hours.",
      inputSchema: {
        file_path: z.string().min(1).describe("Local path to image (JPG, PNG, GIF, WebP)"),
        alt_text: z.string().max(1000).optional().describe("Alt text for accessibility"),
      },
      outputSchema: {
        media_id: z.string(),
        file_path: z.string(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: false,
        idempotentHint: true,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "x_upload_media", request_id: requestId, file: input.file_path }, "tool_call_start");

      try {
        const client = await getXClient(clientId, clientSecret);
        const mediaId = await uploadMedia(client.accessToken, input.file_path, input.alt_text, logger);

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "x_upload_media", request_id: requestId, duration_ms: durationMs, outcome: "success", media_id: mediaId },
          "tool_call_end",
        );

        const result = {
          media_id: mediaId,
          file_path: input.file_path,
        };

        return {
          structuredContent: result,
          content: [{
            type: "text" as const,
            text: `Media uploaded successfully.\n\nMedia ID: ${mediaId}\nFile: ${input.file_path}\n\nThis media_id can be used when drafting a tweet. It expires after ~24 hours.`,
          }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "x_upload_media", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error uploading media: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

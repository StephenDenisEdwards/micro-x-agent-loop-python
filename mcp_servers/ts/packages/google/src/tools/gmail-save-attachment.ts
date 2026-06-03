import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { mkdir, writeFile, readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { getGmailService } from "../auth/google-auth.js";
import {
  getAttachmentBaseDir,
  sanitizeFilename,
  isTextReadable,
  sha256,
  decodeAttachmentData,
} from "../util/attachments.js";

export function registerGmailSaveAttachment(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
): void {
  server.registerTool(
    "gmail_save_attachment",
    {
      description:
        "Download a Gmail attachment to a local file WITHOUT loading its bytes into the conversation. " +
        "Get messageId and attachmentId from gmail_read's attachments list. Returns the saved file " +
        "path and metadata only (size, sha256, mimeType, textReadable). For text-readable files, use " +
        "a filesystem read tool on the returned path if you need the content; binary files (PDFs, " +
        "images) need a separate extraction step.",
      inputSchema: {
        messageId: z.string().describe("The Gmail message ID (from gmail_search/gmail_read)"),
        attachmentId: z.string().describe("The attachment ID (from gmail_read's attachments list)"),
        filename: z
          .string()
          .optional()
          .describe("Filename to save as (from gmail_read); sanitized to a basename. Defaults to a generated name."),
        mimeType: z
          .string()
          .optional()
          .describe("Attachment MIME type (from gmail_read); improves the textReadable hint."),
      },
      annotations: {
        // Reads from Gmail and writes only into the configured attachment dir.
        readOnlyHint: false,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "gmail_save_attachment", request_id: requestId }, "tool_call_start");

      try {
        const filename = sanitizeFilename(input.filename ?? `attachment-${input.attachmentId.slice(0, 16)}.bin`);
        const baseDir = getAttachmentBaseDir();
        const destDir = path.resolve(baseDir, sanitizeFilename(input.messageId));
        const destPath = path.resolve(destDir, filename);

        // Containment guard: the resolved path must stay within destDir.
        if (destPath !== destDir && !destPath.startsWith(destDir + path.sep)) {
          throw new Error("Resolved attachment path escapes the attachment directory");
        }

        const textReadable = isTextReadable(input.mimeType, filename);

        let buf: Buffer;
        let reused = false;

        if (existsSync(destPath)) {
          // (messageId, attachmentId, filename) maps to immutable content, so an
          // existing file is a sound idempotency key — skip the network fetch.
          buf = await readFile(destPath);
          reused = true;
        } else {
          const gmail = await getGmailService(clientId, clientSecret);
          const att = await gmail.users.messages.attachments.get({
            userId: "me",
            messageId: input.messageId,
            id: input.attachmentId,
          });

          const data = att.data.data ?? "";
          if (!data) {
            throw new Error("Attachment returned no data");
          }
          buf = decodeAttachmentData(data);

          await mkdir(destDir, { recursive: true });
          await writeFile(destPath, buf);
        }

        const digest = sha256(buf);

        const result = {
          path: destPath,
          filename,
          messageId: input.messageId,
          attachmentId: input.attachmentId,
          mimeType: input.mimeType ?? "",
          sizeBytes: buf.length,
          sha256: digest,
          textReadable,
          reused,
        };

        const text =
          `Saved attachment to: ${destPath}\n` +
          `  filename:     ${filename}\n` +
          `  sizeBytes:    ${buf.length}\n` +
          `  mimeType:     ${input.mimeType ?? "(unknown)"}\n` +
          `  sha256:       ${digest}\n` +
          `  textReadable: ${textReadable}\n` +
          `  reused:       ${reused}\n` +
          `Bytes were written to disk and NOT loaded into context. ` +
          `${textReadable ? "Use a filesystem read tool on the path above to read the content." : "This is a binary file; reading it as text will not be useful."}`;

        const durationMs = Date.now() - startTime;
        logger.info(
          {
            tool: "gmail_save_attachment",
            request_id: requestId,
            duration_ms: durationMs,
            outcome: "success",
            size_bytes: buf.length,
            reused,
          },
          "tool_call_end",
        );

        return {
          structuredContent: result,
          content: [{ type: "text" as const, text }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          {
            tool: "gmail_save_attachment",
            request_id: requestId,
            duration_ms: durationMs,
            outcome: "error",
            error_message: message,
          },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error saving attachment: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

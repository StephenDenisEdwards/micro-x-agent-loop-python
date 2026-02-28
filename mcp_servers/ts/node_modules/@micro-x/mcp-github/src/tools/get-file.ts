import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import type { Octokit } from "@octokit/rest";

const MAX_CONTENT_CHARS = 100_000;

export function registerGetFile(server: McpServer, logger: Logger, octokit: Octokit): void {
  server.registerTool(
    "get_file",
    {
      description: "Get a file or directory listing from a GitHub repository. Returns decoded file content or a directory listing.",
      inputSchema: {
        repo: z.string().min(1).describe("Repository in owner/repo format"),
        path: z.string().min(1).describe("Path to file or directory within the repository"),
        ref: z.string().describe("Branch, tag, or commit SHA (default: repo default branch)").optional(),
      },
      annotations: { readOnlyHint: true, destructiveHint: false },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "get_file", request_id: requestId, path: input.path }, "tool_call_start");

      try {
        const [owner, repo] = input.repo.split("/");
        const filePath = input.path.replace(/^\/+|\/+$/g, "");

        const resp = await octokit.repos.getContent({
          owner,
          repo,
          path: filePath,
          ref: input.ref,
        });

        const data = resp.data;
        const refStr = input.ref ? ` (ref: ${input.ref})` : "";

        let text: string;
        if (Array.isArray(data)) {
          // Directory listing
          const lines = [`Directory: ${input.repo}/${filePath}${refStr} -- ${data.length} entries`, ""];
          for (const item of data) {
            if (item.type === "dir") lines.push(`  ${item.name}/`);
            else lines.push(`  ${item.name}  (${humanSize(item.size ?? 0)})`);
          }
          text = lines.join("\n");
        } else if ("content" in data && data.type === "file") {
          // File content
          const content = Buffer.from(data.content ?? "", "base64").toString("utf-8");
          const size = data.size ?? 0;
          const truncated = content.length > MAX_CONTENT_CHARS;
          const displayContent = truncated
            ? content.slice(0, MAX_CONTENT_CHARS) + `\n\n... truncated (${humanSize(size)} total)`
            : content;
          text = `File: ${input.repo}/${filePath}${refStr} (${humanSize(size)})\n\n${displayContent}`;
        } else {
          text = `File: ${input.repo}/${filePath}${refStr} -- binary or undecodable content`;
        }

        const durationMs = Date.now() - startTime;
        logger.info({ tool: "get_file", request_id: requestId, duration_ms: durationMs, outcome: "success" }, "tool_call_end");

        return { content: [{ type: "text" as const, text }] };
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        logger.error({ tool: "get_file", request_id: requestId, duration_ms: Date.now() - startTime, outcome: "error" }, "tool_call_end");
        return { content: [{ type: "text" as const, text: `Error getting file: ${message}` }], isError: true };
      }
    },
  );
}

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

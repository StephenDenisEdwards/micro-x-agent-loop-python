import { readFile, rename, stat, open } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { resolveAllowed, requireWritable, type PathPolicy } from "../paths.js";

const BINARY_SNIFF_BYTES = 8 * 1024;
const DEFAULT_MAX_BYTES = 5 * 1024 * 1024;
const EOL_SAMPLE_BYTES = 64 * 1024;
const BOM = Buffer.from([0xef, 0xbb, 0xbf]);

export function registerEditFile(server: McpServer, logger: Logger, policy: PathPolicy): void {
  const maxBytes = parseEnvInt("FILESYSTEM_EDIT_MAX_BYTES", DEFAULT_MAX_BYTES);

  server.registerTool(
    "edit_file",
    {
      description:
        "Surgical exact-string edit to an existing file. Provide enough surrounding context in old_string to make the match unique — uniqueness is enforced (set replace_all=true to apply to every occurrence). " +
        "Do NOT use write_file to change a few lines (it wastes tokens and risks corrupting unrelated content). Do NOT use bash sed/awk. " +
        "write_file is only for creating a new file or replacing its entire contents. " +
        "Line endings (CRLF/LF) are detected from the file and old_string/new_string are normalised to match. UTF-8 BOM is preserved. " +
        "Path must be inside FILESYSTEM_WORKING_DIR or FILESYSTEM_ALLOWED_DIRS. Binary files are refused. Files larger than 5 MB are refused by default (raise via FILESYSTEM_EDIT_MAX_BYTES).",
      inputSchema: {
        path: z.string().min(1).describe("Absolute or relative path to the file to edit"),
        old_string: z.string().describe("Exact text to find. Include enough surrounding context to be unique."),
        new_string: z.string().describe("Replacement text"),
        replace_all: z.boolean().optional().describe("Replace every occurrence of old_string. Default: false (require uniqueness)"),
      },
      outputSchema: {
        path: z.string(),
        replacements: z.number().int(),
      },
      annotations: {
        readOnlyHint: false,
        destructiveHint: true,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();
      const replaceAll = input.replace_all ?? false;

      logger.info(
        {
          tool: "edit_file",
          request_id: requestId,
          path: input.path,
          replace_all: replaceAll,
          old_len: input.old_string.length,
          new_len: input.new_string.length,
        },
        "tool_call_start",
      );

      try {
        if (input.old_string.length === 0) {
          return errorResult("old_string is empty — provide the exact text to replace");
        }
        if (input.old_string === input.new_string) {
          return errorResult("old_string and new_string are identical — refusing no-op");
        }

        const resolvedPath = await resolveAllowed(policy, input.path, { mustExist: false });
        await requireWritable(policy, resolvedPath);

        let st;
        try {
          st = await stat(resolvedPath);
        } catch {
          return errorResult(`file not found: ${resolvedPath}`);
        }
        if (!st.isFile()) {
          return errorResult(`not a regular file: ${resolvedPath}`);
        }
        if (st.size > maxBytes) {
          return errorResult(
            `file too large for edit_file (${st.size} bytes > ${maxBytes}) — use write_file or split the edit`,
          );
        }

        const buf = await readFile(resolvedPath);
        if (isBinary(buf)) {
          return errorResult(
            `refusing to edit binary file: ${resolvedPath} (null byte detected in first ${BINARY_SNIFF_BYTES} bytes)`,
          );
        }

        const hasBOM = buf.length >= 3 && buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf;
        const text = buf.toString("utf-8", hasBOM ? 3 : 0);

        const eol = detectEOL(text);
        const oldNorm = normaliseEOL(input.old_string, eol);
        const newNorm = normaliseEOL(input.new_string, eol);

        const count = countOccurrences(text, oldNorm);
        if (count === 0) {
          return errorResult(`old_string not found in ${resolvedPath}`);
        }
        if (count > 1 && !replaceAll) {
          return errorResult(
            `old_string is not unique (${count} matches) in ${resolvedPath} — add surrounding context or set replace_all=true`,
          );
        }

        let updated: string;
        let replacements: number;
        if (replaceAll) {
          updated = text.split(oldNorm).join(newNorm);
          replacements = count;
        } else {
          const idx = text.indexOf(oldNorm);
          updated = text.slice(0, idx) + newNorm + text.slice(idx + oldNorm.length);
          replacements = 1;
        }

        const updatedBuf = hasBOM
          ? Buffer.concat([BOM, Buffer.from(updated, "utf-8")])
          : Buffer.from(updated, "utf-8");

        await atomicWrite(resolvedPath, updatedBuf, st.mode);

        const durationMs = Date.now() - startTime;
        logger.info(
          {
            tool: "edit_file",
            request_id: requestId,
            duration_ms: durationMs,
            outcome: "success",
            replacements,
            new_size: updatedBuf.length,
          },
          "tool_call_end",
        );

        const tail = replacements === 1 ? "" : "s";
        return {
          structuredContent: { path: resolvedPath, replacements },
          content: [
            {
              type: "text" as const,
              text: `edited ${resolvedPath}: ${replacements} replacement${tail}`,
            },
          ],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);
        logger.error(
          {
            tool: "edit_file",
            request_id: requestId,
            duration_ms: durationMs,
            outcome: "error",
            error_message: message,
          },
          "tool_call_end",
        );
        return errorResult(`Error editing file: ${message}`);
      }
    },
  );
}

function errorResult(text: string) {
  return { content: [{ type: "text" as const, text }], isError: true };
}

function isBinary(buf: Buffer): boolean {
  const len = Math.min(buf.length, BINARY_SNIFF_BYTES);
  for (let i = 0; i < len; i++) {
    if (buf[i] === 0) return true;
  }
  return false;
}

function detectEOL(text: string): "\r\n" | "\n" {
  const sample = text.length > EOL_SAMPLE_BYTES ? text.slice(0, EOL_SAMPLE_BYTES) : text;
  return sample.includes("\r\n") ? "\r\n" : "\n";
}

function normaliseEOL(s: string, target: "\r\n" | "\n"): string {
  const lf = s.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  return target === "\n" ? lf : lf.replace(/\n/g, "\r\n");
}

function countOccurrences(haystack: string, needle: string): number {
  if (needle.length === 0) return 0;
  let count = 0;
  let pos = 0;
  while (true) {
    const found = haystack.indexOf(needle, pos);
    if (found === -1) return count;
    count++;
    pos = found + needle.length;
  }
}

async function atomicWrite(filePath: string, content: Buffer, mode: number): Promise<void> {
  const dir = path.dirname(filePath);
  const base = path.basename(filePath);
  const tempName = `.${base}.${crypto.randomUUID()}.tmp`;
  const tempPath = path.join(dir, tempName);

  // mode & 0o777 strips file-type bits; we only want permission bits.
  const handle = await open(tempPath, "w", mode & 0o777);
  try {
    await handle.writeFile(content);
    await handle.sync();
  } finally {
    await handle.close();
  }

  await rename(tempPath, filePath);
}

function parseEnvInt(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const n = parseInt(raw, 10);
  if (Number.isNaN(n) || n <= 0) return fallback;
  return n;
}

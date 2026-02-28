import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { ValidationError, UpstreamError } from "@micro-x/mcp-shared";

const BASE_URL = "https://api.anthropic.com/v1/organizations";

const ENDPOINTS: Record<string, string> = {
  usage: "/usage_report/messages",
  cost: "/cost_report",
  claude_code: "/usage_report/claude_code",
};

const REPORT_LABELS: Record<string, string> = {
  usage: "Token Usage Report",
  cost: "Cost Report",
  claude_code: "Claude Code Usage Report",
};

/**
 * Recursively convert 'amount' fields from cents to USD in-place.
 */
function convertCostAmounts(data: Record<string, unknown>): void {
  for (const key of Object.keys(data)) {
    if (key === "amount" && "currency" in data) {
      const cents = Number(data[key]);
      delete data[key];
      data.amount_usd = Math.round(cents) / 100;
    } else if (typeof data[key] === "object" && data[key] !== null) {
      if (Array.isArray(data[key])) {
        for (const item of data[key] as unknown[]) {
          if (typeof item === "object" && item !== null) {
            convertCostAmounts(item as Record<string, unknown>);
          }
        }
      } else {
        convertCostAmounts(data[key] as Record<string, unknown>);
      }
    }
  }
}

export function registerUsage(server: McpServer, logger: Logger, adminApiKey: string): void {
  server.registerTool(
    "anthropic_usage",
    {
      description:
        "Query Anthropic Admin API for organization usage and cost reports. " +
        "Supports three actions: 'usage' (token-level usage), 'cost' (spend in USD, converted from cents), " +
        "'claude_code' (Claude Code productivity metrics).",
      inputSchema: {
        action: z.enum(["usage", "cost", "claude_code"]).describe(
          "Which report: 'usage' (token usage), 'cost' (spend in USD), 'claude_code' (productivity metrics)",
        ),
        starting_at: z.string().min(1).describe(
          "Start time — RFC 3339 for usage/cost (e.g. '2025-02-01T00:00:00Z'), YYYY-MM-DD for claude_code",
        ),
        ending_at: z.string().describe("Optional end time (same format as starting_at)").optional(),
        bucket_width: z
          .enum(["1m", "1h", "1d"])
          .describe("Time granularity: '1m', '1h', or '1d'")
          .optional(),
        group_by: z
          .array(z.string())
          .describe("Group results by fields (e.g. ['model', 'workspace_id'])")
          .optional(),
        limit: z.number().int().min(1).describe("Max number of time buckets / records to return").optional(),
      },
      outputSchema: {
        report_type: z.string(),
        data: z.record(z.unknown()),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "anthropic_usage", request_id: requestId, action: input.action }, "tool_call_start");

      try {
        const endpoint = ENDPOINTS[input.action];
        if (!endpoint) {
          throw new ValidationError(`Unknown action '${input.action}'`);
        }

        const url = new URL(BASE_URL + endpoint);
        url.searchParams.set("starting_at", input.starting_at);
        if (input.ending_at) url.searchParams.set("ending_at", input.ending_at);
        if (input.bucket_width) url.searchParams.set("bucket_width", input.bucket_width);
        if (input.group_by) {
          for (const field of input.group_by) {
            url.searchParams.append("group_by[]", field);
          }
        }
        if (input.limit) url.searchParams.set("limit", String(input.limit));

        const response = await fetch(url.toString(), {
          headers: {
            "x-api-key": adminApiKey,
            "anthropic-version": "2023-06-01",
          },
        });

        if (response.status !== 200) {
          const text = await response.text();
          throw new UpstreamError(`HTTP ${response.status} — ${text}`, response.status);
        }

        const data = (await response.json()) as Record<string, unknown>;
        const label = REPORT_LABELS[input.action];

        if (input.action === "cost") {
          convertCostAmounts(data);
        }

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "anthropic_usage", request_id: requestId, duration_ms: durationMs, outcome: "success" },
          "tool_call_end",
        );

        return {
          structuredContent: { report_type: input.action, data },
          content: [{ type: "text" as const, text: `${label}:\n${JSON.stringify(data, null, 2)}` }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "anthropic_usage", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error querying Anthropic Admin API: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

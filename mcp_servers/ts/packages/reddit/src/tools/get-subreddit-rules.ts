import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x-ai/mcp-shared";
import { getRedditAuth } from "../auth/reddit-auth.js";

export function registerGetSubredditRules(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
  username: string,
  password: string,
  userAgent: string,
): void {
  server.registerTool(
    "reddit_get_subreddit_rules",
    {
      description:
        "Get the rules and post requirements for a subreddit. " +
        "Returns both community rules and posting requirements " +
        "(flair required, body restrictions, title constraints, etc.).",
      inputSchema: {
        subreddit: z.string().min(1).describe("Subreddit name (without r/ prefix)"),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "reddit_get_subreddit_rules", request_id: requestId, subreddit: input.subreddit }, "tool_call_start");

      try {
        const auth = await getRedditAuth(clientId, clientSecret, username, password, userAgent);

        // Fetch both rules and post requirements in parallel
        const [rulesResponse, requirementsResponse] = await Promise.all([
          resilientFetch(
            `https://oauth.reddit.com/r/${input.subreddit}/about/rules`,
            {
              headers: {
                "Authorization": `Bearer ${auth.accessToken}`,
                "User-Agent": userAgent,
              },
            },
            { timeoutMs: 15_000, retries: 2 },
          ),
          resilientFetch(
            `https://oauth.reddit.com/api/v1/${input.subreddit}/post_requirements`,
            {
              headers: {
                "Authorization": `Bearer ${auth.accessToken}`,
                "User-Agent": userAgent,
              },
            },
            { timeoutMs: 15_000, retries: 2 },
          ),
        ]);

        if (!rulesResponse.ok) {
          const errorText = await rulesResponse.text();
          throw new UpstreamError(
            `Reddit rules API error (${rulesResponse.status}): ${errorText}`,
            rulesResponse.status,
          );
        }

        if (!requirementsResponse.ok) {
          const errorText = await requirementsResponse.text();
          throw new UpstreamError(
            `Reddit post requirements API error (${requirementsResponse.status}): ${errorText}`,
            requirementsResponse.status,
          );
        }

        const rulesData = await rulesResponse.json() as {
          rules: Array<{
            kind: string;
            short_name: string;
            description: string;
            violation_reason: string;
            created_utc: number;
            priority: number;
          }>;
          site_rules: string[];
        };

        const requirementsData = await requirementsResponse.json() as {
          is_flair_required: boolean;
          body_restriction_policy: string;
          domain_blacklist: string[];
          domain_whitelist: string[];
          title_text_min_length: number | null;
          title_text_max_length: number | null;
          body_text_min_length: number | null;
          body_text_max_length: number | null;
          title_required_strings: string[];
          body_required_strings: string[];
          title_blacklisted_strings: string[];
          body_blacklisted_strings: string[];
          guidelines_text: string | null;
          guidelines_display_policy: string | null;
        };

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "reddit_get_subreddit_rules", request_id: requestId, duration_ms: durationMs, outcome: "success", rule_count: rulesData.rules.length },
          "tool_call_end",
        );

        const rules = rulesData.rules.map(r => ({
          kind: r.kind,
          short_name: r.short_name,
          description: r.description,
          violation_reason: r.violation_reason,
        }));

        const result = {
          subreddit: input.subreddit,
          rules,
          rule_count: rules.length,
          post_requirements: {
            is_flair_required: requirementsData.is_flair_required,
            body_restriction_policy: requirementsData.body_restriction_policy,
            domain_blacklist: requirementsData.domain_blacklist,
            domain_whitelist: requirementsData.domain_whitelist,
            title_text_min_length: requirementsData.title_text_min_length,
            title_text_max_length: requirementsData.title_text_max_length,
            body_text_min_length: requirementsData.body_text_min_length,
            body_text_max_length: requirementsData.body_text_max_length,
            title_required_strings: requirementsData.title_required_strings,
            body_required_strings: requirementsData.body_required_strings,
            title_blacklisted_strings: requirementsData.title_blacklisted_strings,
            body_blacklisted_strings: requirementsData.body_blacklisted_strings,
            guidelines_text: requirementsData.guidelines_text,
          },
        };

        // Build text summary
        const lines: string[] = [`r/${input.subreddit} — Rules & Post Requirements`, ""];

        if (rules.length > 0) {
          lines.push("=== Community Rules ===");
          for (const [i, rule] of rules.entries()) {
            lines.push(`${i + 1}. ${rule.short_name}`);
            if (rule.description) {
              lines.push(`   ${rule.description.substring(0, 200)}`);
            }
          }
          lines.push("");
        }

        lines.push("=== Post Requirements ===");
        lines.push(`Flair required: ${requirementsData.is_flair_required ? "Yes" : "No"}`);
        lines.push(`Body policy: ${requirementsData.body_restriction_policy}`);

        if (requirementsData.title_text_min_length != null) {
          lines.push(`Title min length: ${requirementsData.title_text_min_length}`);
        }
        if (requirementsData.title_text_max_length != null) {
          lines.push(`Title max length: ${requirementsData.title_text_max_length}`);
        }
        if (requirementsData.body_text_min_length != null) {
          lines.push(`Body min length: ${requirementsData.body_text_min_length}`);
        }
        if (requirementsData.body_text_max_length != null) {
          lines.push(`Body max length: ${requirementsData.body_text_max_length}`);
        }

        if (requirementsData.domain_blacklist?.length > 0) {
          lines.push(`Blocked domains: ${requirementsData.domain_blacklist.join(", ")}`);
        }

        if (requirementsData.guidelines_text) {
          lines.push("", `Guidelines: ${requirementsData.guidelines_text}`);
        }

        return {
          structuredContent: result,
          content: [{
            type: "text" as const,
            text: lines.join("\n"),
          }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "reddit_get_subreddit_rules", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error fetching subreddit rules: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

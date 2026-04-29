import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x-ai/mcp-shared";
import { getRedditAuth } from "../auth/reddit-auth.js";

export function registerGetMyPosts(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
  username: string,
  password: string,
  userAgent: string,
): void {
  server.registerTool(
    "reddit_get_my_posts",
    {
      description: "List the authenticated user's own Reddit submissions.",
      inputSchema: {
        sort: z
          .enum(["hot", "new", "top", "controversial"])
          .default("new")
          .optional()
          .describe("Sort order (default 'new')"),
        time: z
          .enum(["hour", "day", "week", "month", "year", "all"])
          .optional()
          .describe("Time filter for top/controversial sorts"),
        limit: z
          .number()
          .int()
          .min(1)
          .max(100)
          .default(25)
          .optional()
          .describe("Max posts to return (default 25, max 100)"),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "reddit_get_my_posts", request_id: requestId }, "tool_call_start");

      try {
        const auth = await getRedditAuth(clientId, clientSecret, username, password, userAgent);

        const sort = input.sort ?? "new";
        const limit = input.limit ?? 25;

        const params = new URLSearchParams({
          sort,
          limit: limit.toString(),
        });
        if (input.time) {
          params.set("t", input.time);
        }

        const response = await resilientFetch(
          `https://oauth.reddit.com/user/${auth.username}/submitted?${params.toString()}`,
          {
            headers: {
              "Authorization": `Bearer ${auth.accessToken}`,
              "User-Agent": userAgent,
            },
          },
          { timeoutMs: 15_000, retries: 2 },
        );

        if (!response.ok) {
          const errorText = await response.text();
          throw new UpstreamError(
            `Reddit API error (${response.status}): ${errorText}`,
            response.status,
          );
        }

        const listing = await response.json() as {
          data: {
            children: Array<{
              data: {
                name: string;
                title: string;
                subreddit: string;
                score: number;
                upvote_ratio: number;
                num_comments: number;
                created_utc: number;
                url: string;
                permalink: string;
                selftext: string;
                link_flair_text: string | null;
                is_self: boolean;
                over_18: boolean;
              };
            }>;
            after: string | null;
          };
        };

        const posts = listing.data.children.map(c => ({
          fullname: c.data.name,
          title: c.data.title,
          subreddit: c.data.subreddit,
          score: c.data.score,
          upvote_ratio: c.data.upvote_ratio,
          num_comments: c.data.num_comments,
          created_utc: c.data.created_utc,
          url: c.data.url,
          permalink: `https://www.reddit.com${c.data.permalink}`,
          is_self: c.data.is_self,
          flair: c.data.link_flair_text,
          nsfw: c.data.over_18,
        }));

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "reddit_get_my_posts", request_id: requestId, duration_ms: durationMs, outcome: "success", post_count: posts.length },
          "tool_call_end",
        );

        const result = {
          username: auth.username,
          sort,
          posts,
          post_count: posts.length,
          after: listing.data.after,
        };

        const lines = posts.map((p, i) => {
          const titlePreview = p.title.length > 80 ? p.title.substring(0, 80) + "..." : p.title;
          return `${i + 1}. [r/${p.subreddit}] ${titlePreview}\n   ${p.score} pts | ${p.num_comments} comments | ${new Date(p.created_utc * 1000).toISOString()}`;
        });

        return {
          structuredContent: result,
          content: [{
            type: "text" as const,
            text: posts.length > 0
              ? `Your submissions (${posts.length}):\n\n${lines.join("\n\n")}`
              : "No submissions found.",
          }],
        };
      } catch (err: unknown) {
        const durationMs = Date.now() - startTime;
        const message = err instanceof Error ? err.message : String(err);

        logger.error(
          { tool: "reddit_get_my_posts", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error fetching your posts: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

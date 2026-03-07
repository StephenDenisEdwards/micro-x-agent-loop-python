import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x/mcp-shared";
import { UpstreamError, resilientFetch } from "@micro-x/mcp-shared";
import { getRedditAuth } from "../auth/reddit-auth.js";

export function registerGetPost(
  server: McpServer,
  logger: Logger,
  clientId: string,
  clientSecret: string,
  username: string,
  password: string,
  userAgent: string,
): void {
  server.registerTool(
    "reddit_get_post",
    {
      description:
        "Get a Reddit post and its comments. Returns the post details " +
        "and a tree of comments sorted by the specified order.",
      inputSchema: {
        subreddit: z.string().min(1).describe("Subreddit name (without r/ prefix)"),
        post_id: z.string().min(1).describe("Post ID (bare ID without t3_ prefix)"),
        comment_sort: z
          .enum(["best", "top", "new", "controversial", "old", "q&a"])
          .default("best")
          .optional()
          .describe("Comment sort order (default 'best')"),
        comment_limit: z
          .number()
          .int()
          .min(1)
          .max(500)
          .default(50)
          .optional()
          .describe("Max comments to return (default 50, max 500)"),
      },
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
      },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "reddit_get_post", request_id: requestId, post_id: input.post_id }, "tool_call_start");

      try {
        const auth = await getRedditAuth(clientId, clientSecret, username, password, userAgent);

        const sort = input.comment_sort ?? "best";
        const limit = input.comment_limit ?? 50;

        const params = new URLSearchParams({
          sort,
          limit: limit.toString(),
        });

        const response = await resilientFetch(
          `https://oauth.reddit.com/r/${input.subreddit}/comments/${input.post_id}?${params.toString()}`,
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

        // Response is array of 2 Listings: [0] = post, [1] = comments
        const listings = await response.json() as [
          {
            data: {
              children: Array<{
                data: {
                  name: string;
                  title: string;
                  selftext: string;
                  author: string;
                  score: number;
                  upvote_ratio: number;
                  num_comments: number;
                  created_utc: number;
                  url: string;
                  permalink: string;
                  link_flair_text: string | null;
                  is_self: boolean;
                };
              }>;
            };
          },
          {
            data: {
              children: Array<{
                kind: string;
                data: {
                  name: string;
                  author: string;
                  body: string;
                  score: number;
                  created_utc: number;
                  depth: number;
                  parent_id: string;
                };
              }>;
            };
          },
        ];

        const postData = listings[0].data.children[0].data;
        const comments = listings[1].data.children
          .filter(c => c.kind === "t1") // exclude "more" stubs
          .map(c => ({
            fullname: c.data.name,
            author: c.data.author,
            body: c.data.body,
            score: c.data.score,
            created_utc: c.data.created_utc,
            depth: c.data.depth,
            parent_id: c.data.parent_id,
          }));

        const durationMs = Date.now() - startTime;
        logger.info(
          { tool: "reddit_get_post", request_id: requestId, duration_ms: durationMs, outcome: "success", comment_count: comments.length },
          "tool_call_end",
        );

        const result = {
          post: {
            fullname: postData.name,
            title: postData.title,
            author: postData.author,
            selftext: postData.selftext,
            score: postData.score,
            upvote_ratio: postData.upvote_ratio,
            num_comments: postData.num_comments,
            created_utc: postData.created_utc,
            url: postData.url,
            permalink: `https://www.reddit.com${postData.permalink}`,
            flair: postData.link_flair_text,
            is_self: postData.is_self,
          },
          comments,
          comment_count: comments.length,
        };

        // Build text preview
        const lines: string[] = [
          `r/${input.subreddit} — ${postData.title}`,
          `by u/${postData.author} | Score: ${postData.score} (${Math.round(postData.upvote_ratio * 100)}% upvoted) | ${postData.num_comments} comments`,
          `Posted: ${new Date(postData.created_utc * 1000).toISOString()}`,
        ];

        if (postData.link_flair_text) {
          lines.push(`Flair: ${postData.link_flair_text}`);
        }

        if (postData.is_self && postData.selftext) {
          const bodyPreview = postData.selftext.length > 500
            ? postData.selftext.substring(0, 500) + "..."
            : postData.selftext;
          lines.push("", bodyPreview);
        } else if (!postData.is_self) {
          lines.push(`Link: ${postData.url}`);
        }

        if (comments.length > 0) {
          lines.push("", `--- Comments (${comments.length}) ---`);
          for (const c of comments.slice(0, 20)) {
            const indent = "  ".repeat(c.depth);
            const bodyPreview = c.body.length > 200
              ? c.body.substring(0, 200) + "..."
              : c.body;
            lines.push(`${indent}u/${c.author} (${c.score} pts): ${bodyPreview}`);
          }
          if (comments.length > 20) {
            lines.push(`... and ${comments.length - 20} more comments`);
          }
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
          { tool: "reddit_get_post", request_id: requestId, duration_ms: durationMs, outcome: "error", error_message: message },
          "tool_call_end",
        );

        return {
          content: [{ type: "text" as const, text: `Error fetching post: ${message}` }],
          isError: true,
        };
      }
    },
  );
}

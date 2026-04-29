import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { Logger } from "@micro-x-ai/mcp-shared";
import type { graphql } from "@octokit/graphql";
import { getRepoNodeId, resolveCategoryId, resolveLabelIds, getDiscussionCategories } from "../graphql/client.js";

export function registerCreateDiscussion(server: McpServer, logger: Logger, gql: typeof graphql): void {
  server.registerTool(
    "create_discussion",
    {
      description: "Create a new discussion in a GitHub repository.",
      inputSchema: {
        repo: z.string().min(1).describe("Repository in owner/repo format"),
        title: z.string().min(1).describe("Discussion title"),
        body: z.string().min(1).describe("Discussion body (GitHub Flavored Markdown)"),
        category: z.string().min(1).describe("Category name (e.g., General, Ideas, Q&A, Show and tell). Use get_discussion_categories to list valid options"),
        labels: z.array(z.string()).describe("Label names to apply").optional(),
      },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false },
    },
    async (input) => {
      const startTime = Date.now();
      const requestId = crypto.randomUUID();

      logger.info({ tool: "create_discussion", request_id: requestId }, "tool_call_start");

      try {
        const [owner, repo] = input.repo.split("/");

        // Resolve category
        const category = await resolveCategoryId(gql, owner, repo, input.category);
        if (!category) {
          const categories = await getDiscussionCategories(gql, owner, repo);
          if (categories.length === 0) {
            return {
              content: [{ type: "text" as const, text: `Discussions are not enabled for ${input.repo}. Enable them in Settings > Features > Discussions.` }],
              isError: true,
            };
          }
          const validNames = categories.map((c) => c.name).join(", ");
          return {
            content: [{ type: "text" as const, text: `Invalid category "${input.category}". Valid categories: ${validNames}` }],
            isError: true,
          };
        }

        // Resolve repo node ID
        const repositoryId = await getRepoNodeId(gql, owner, repo);

        // Create discussion
        const result = await gql<{
          createDiscussion: {
            discussion: {
              id: string;
              number: number;
              url: string;
              title: string;
              createdAt: string;
              category: { name: string; isAnswerable: boolean };
            };
          };
        }>(
          `mutation CreateDiscussion($repositoryId: ID!, $categoryId: ID!, $title: String!, $body: String!) {
            createDiscussion(input: {
              repositoryId: $repositoryId
              categoryId: $categoryId
              title: $title
              body: $body
            }) {
              discussion {
                id number url title createdAt
                category { name isAnswerable }
              }
            }
          }`,
          { repositoryId, categoryId: category.id, title: input.title, body: input.body },
        );

        const discussion = result.createDiscussion.discussion;
        let appliedLabels: string[] = [];

        // Apply labels if provided (requires separate mutation)
        if (input.labels && input.labels.length > 0) {
          const resolved = await resolveLabelIds(gql, owner, repo, input.labels);
          if (resolved.length > 0) {
            await gql(
              `mutation AddLabels($labelableId: ID!, $labelIds: [ID!]!) {
                addLabelsToLabelable(input: { labelableId: $labelableId, labelIds: $labelIds }) {
                  clientMutationId
                }
              }`,
              { labelableId: discussion.id, labelIds: resolved.map((l) => l.id) },
            );
            appliedLabels = resolved.map((l) => l.name);
          }
        }

        const structured = {
          success: true,
          number: discussion.number,
          url: discussion.url,
          title: discussion.title,
          category: discussion.category.name,
          labels: appliedLabels,
        };

        const labelText = appliedLabels.length > 0 ? ` [${appliedLabels.join(", ")}]` : "";
        const text = `Discussion created: #${discussion.number} — ${discussion.title}${labelText}\nCategory: ${discussion.category.name}\n${discussion.url}`;

        const durationMs = Date.now() - startTime;
        logger.info({ tool: "create_discussion", request_id: requestId, duration_ms: durationMs, outcome: "success" }, "tool_call_end");

        return {
          structuredContent: structured,
          content: [{ type: "text" as const, text }],
        };
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        logger.error({ tool: "create_discussion", request_id: requestId, duration_ms: Date.now() - startTime, outcome: "error" }, "tool_call_end");
        return { content: [{ type: "text" as const, text: `Error creating discussion: ${message}` }], isError: true };
      }
    },
  );
}

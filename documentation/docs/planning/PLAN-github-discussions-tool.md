# Plan: GitHub Discussions Tools (Extension to GitHub MCP Server)

**Status: Completed**

## Context

The agent needs to create and manage GitHub Discussions for community engagement around the micro-x-agent-loop-python repo. Discussions are useful for posting architecture insights, announcing features, and engaging with technical audiences directly on the repo.

This is **not a new MCP server** — it adds tools to the existing GitHub MCP server (`mcp_servers/ts/packages/github/`). GitHub Discussions are GraphQL-only (no REST API), so these tools use the GraphQL endpoint alongside the existing REST-based tools.

## API: GitHub GraphQL

**Endpoint:** `POST https://api.github.com/graphql`

**Auth:** Same `GITHUB_TOKEN` (Bearer token) already used by the GitHub MCP server. No additional credentials needed.

**Required PAT scopes:** The existing `repo` scope (Classic PAT) or `Discussions: Read and write` (Fine-grained PAT) covers discussions. No new permissions needed if the token already has `repo` scope.

### GraphQL vs REST

The existing GitHub tools use REST via Octokit. Discussions tools must use GraphQL because GitHub provides no REST endpoints for discussions. Both can coexist in the same MCP server — the server instantiates both an Octokit REST client and a GraphQL client from the same token.

**GraphQL client:** Use `@octokit/graphql` (part of the Octokit ecosystem, already available as a transitive dependency of `@octokit/rest`).

```typescript
import { graphql } from "@octokit/graphql";

const gql = graphql.defaults({
  headers: { authorization: `bearer ${process.env.GITHUB_TOKEN}` },
});
```

### Node IDs

GraphQL mutations require node IDs (opaque strings like `R_kgDOABCDEF`, `DIC_kwDOABCDEF4ABCD12`), not integer IDs. The server must:
1. Resolve the repository node ID from `owner/repo` (cache after first call)
2. Resolve category IDs by listing categories (cache per repo)

## Tool Definitions

### `github_create_discussion`

Create a new discussion in a repository.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo` | string | yes | Repository (`owner/repo`) |
| `title` | string | yes | Discussion title |
| `body` | string | yes | Discussion body (GitHub Flavored Markdown) |
| `category` | string | yes | Category name (e.g., `General`, `Ideas`, `Q&A`, `Show and tell`). Resolved to category node ID internally |
| `labels` | string[] | no | Label names to apply (resolved to node IDs; applied via separate `addLabelsToLabelable` mutation) |

**Implementation:**
1. Resolve repo node ID: `query { repository(owner, name) { id } }`
2. Resolve category ID: `query { repository.discussionCategories(first: 25) }` — match by name (case-insensitive)
3. Create discussion: `mutation { createDiscussion(input: { repositoryId, categoryId, title, body }) }`
4. If `labels` provided: resolve label IDs via `query { repository.labels }`, then `mutation { addLabelsToLabelable(labelableId, labelIds) }`

**Gotcha:** Labels cannot be set atomically in `createDiscussion` — the GraphQL input type has no `labelIds` field. This is a known GitHub API limitation. The two-step approach (create + add labels) is the only option.

**GraphQL mutation:**
```graphql
mutation CreateDiscussion($repositoryId: ID!, $categoryId: ID!, $title: String!, $body: String!) {
  createDiscussion(input: {
    repositoryId: $repositoryId
    categoryId: $categoryId
    title: $title
    body: $body
  }) {
    discussion {
      id
      number
      url
      title
      createdAt
      category { name isAnswerable }
    }
  }
}
```

**MCP annotations:** `readOnlyHint: false`, `destructiveHint: false`, `idempotentHint: false`

### `github_list_discussions`

List discussions in a repository with optional filters.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo` | string | yes | Repository (`owner/repo`) |
| `category` | string | no | Filter by category name |
| `answered` | boolean | no | Filter Q&A discussions: `true` = answered only, `false` = unanswered only |
| `sort` | string | no | `CREATED_AT` (default) or `UPDATED_AT` |
| `direction` | string | no | `DESC` (default) or `ASC` |
| `max_results` | number | no | Number of results (default 10, max 100) |

**GraphQL query:**
```graphql
query ListDiscussions($owner: String!, $name: String!, $first: Int!, $categoryId: ID, $answered: Boolean, $orderBy: DiscussionOrder) {
  repository(owner: $owner, name: $name) {
    discussions(first: $first, categoryId: $categoryId, answered: $answered, orderBy: $orderBy) {
      totalCount
      nodes {
        id
        number
        title
        createdAt
        updatedAt
        url
        isAnswered
        category { name }
        author { login }
        comments { totalCount }
        labels(first: 5) { nodes { name } }
      }
    }
  }
}
```

**Note:** The `discussions()` field does not support filtering by label or author. For those, use the `search` query type as a fallback: `search(query: "repo:owner/name is:open label:bug", type: DISCUSSION)`.

### `github_get_discussion`

Get a discussion with its comments.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo` | string | yes | Repository (`owner/repo`) |
| `number` | number | yes | Discussion number (from URL or list) |
| `comment_limit` | number | no | Max comments to return (default 20, max 100) |

**GraphQL query:**
```graphql
query GetDiscussion($owner: String!, $name: String!, $number: Int!, $commentLimit: Int!) {
  repository(owner: $owner, name: $name) {
    discussion(number: $number) {
      id
      number
      title
      body
      createdAt
      updatedAt
      url
      isAnswered
      answer {
        id
        body
        author { login }
        createdAt
      }
      category { name isAnswerable }
      author { login }
      labels(first: 10) { nodes { name color } }
      comments(first: $commentLimit) {
        totalCount
        nodes {
          id
          body
          createdAt
          isAnswer
          author { login }
          replies(first: 5) {
            totalCount
            nodes {
              id
              body
              author { login }
              createdAt
            }
          }
        }
      }
    }
  }
}
```

Returns `null` (not an error) if the discussion number doesn't exist. The server should return a clear "Discussion #N not found" message.

### `github_comment_on_discussion`

Add a comment or reply to a discussion.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo` | string | yes | Repository (`owner/repo`) — used to validate context, not in the mutation |
| `discussion_id` | string | yes | Discussion node ID (from `github_get_discussion` or `github_list_discussions`) |
| `body` | string | yes | Comment body (GitHub Flavored Markdown) |
| `reply_to_id` | string | no | Comment node ID to reply to (for threaded replies). Omit for top-level comment |

**GraphQL mutation:**
```graphql
mutation AddComment($discussionId: ID!, $body: String!, $replyToId: ID) {
  addDiscussionComment(input: {
    discussionId: $discussionId
    body: $body
    replyToId: $replyToId
  }) {
    comment {
      id
      url
      body
      createdAt
      author { login }
      isAnswer
    }
  }
}
```

**Gotcha:** `replyToId` must be a top-level comment node ID (`DC_...`). Replies-to-replies are not supported — GitHub flattens all threaded replies under the parent comment.

**MCP annotations:** `readOnlyHint: false`, `destructiveHint: false`, `idempotentHint: false`

### `github_get_discussion_categories`

List available discussion categories for a repository.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `repo` | string | yes | Repository (`owner/repo`) |

**GraphQL query:**
```graphql
query GetCategories($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    discussionCategories(first: 25) {
      nodes {
        id
        name
        emoji
        description
        isAnswerable
      }
    }
  }
}
```

Useful for the agent to discover valid categories before creating a discussion. Repos can have at most 25 categories.

## Output Schemas

### Discussion creation response
```json
{
  "success": true,
  "number": 42,
  "url": "https://github.com/owner/repo/discussions/42",
  "title": "Cost-Aware Agent Architecture: Discussion",
  "category": "Show and tell",
  "labels": ["architecture", "cost-optimization"]
}
```

### Discussion list response
```json
{
  "total_count": 15,
  "discussions": [
    {
      "number": 42,
      "title": "...",
      "url": "...",
      "category": "Show and tell",
      "author": "username",
      "created_at": "2026-03-04T10:00:00Z",
      "is_answered": false,
      "comment_count": 5,
      "labels": ["architecture"]
    }
  ]
}
```

### Discussion detail response
```json
{
  "number": 42,
  "title": "...",
  "body": "...",
  "url": "...",
  "category": "Show and tell",
  "is_answerable": false,
  "is_answered": false,
  "author": "username",
  "created_at": "2026-03-04T10:00:00Z",
  "labels": ["architecture"],
  "comment_count": 3,
  "comments": [
    {
      "id": "DC_kwDOABCDEF4ABCD34",
      "author": "commenter",
      "body": "...",
      "created_at": "2026-03-04T12:00:00Z",
      "is_answer": false,
      "reply_count": 1
    }
  ]
}
```

## Implementation Notes

### Integration into existing GitHub MCP server

The GitHub MCP server already exists at `mcp_servers/ts/packages/github/`. These tools are added as new tool handlers alongside the existing REST-based tools.

**New files:**
```
mcp_servers/ts/packages/github/src/
  tools/
    create-discussion.ts        # NEW
    list-discussions.ts          # NEW
    get-discussion.ts            # NEW
    comment-on-discussion.ts     # NEW
    get-discussion-categories.ts # NEW
    ... (existing REST tools)
  graphql/
    client.ts                    # NEW — shared GraphQL client setup
    queries.ts                   # NEW — query/mutation strings
```

**Server entry point (`index.ts`):** Register the 5 new tools in the tool handler map alongside existing tools. No new server process — same MCP server, same config entry.

### Caching

- **Repository node ID:** Cache after first resolution per `owner/repo`. Unlikely to change.
- **Category IDs:** Cache per repo per session. Categories rarely change.
- **Label IDs:** Cache per repo per session.

### Error Handling

- **Discussion not found:** `discussion(number: N)` returns `null`, not an error. Return "Discussion #N not found in owner/repo".
- **Invalid category:** If the category name doesn't match any `discussionCategories`, return an error listing valid category names.
- **Discussions not enabled:** Some repos don't have Discussions enabled. The `discussionCategories` query returns an empty list. Return "Discussions are not enabled for owner/repo".
- **GraphQL errors:** The response body includes an `errors` array alongside `data`. Always check for errors even when `data` is present (partial failures are possible).

## Rate Limits

GraphQL shares the same rate limit pool as REST:

| Metric | Limit |
|--------|-------|
| Points per hour | 5,000 (standard user) |
| Points per minute | 2,000 (secondary limit) |
| Cost per query | 1 point |
| Cost per mutation | 5 points |
| Content-creating mutations | 80/minute, 500/hour |

At 5 points per mutation, creating a discussion + adding labels = 10 points. The 5,000/hour budget allows ~500 create operations per hour — more than sufficient.

**Inline rate limit check:** Include `rateLimit { remaining resetAt }` in queries to monitor budget without extra API calls.

## Key Gotchas

1. **GraphQL-only.** No REST endpoints for discussions. Must use `POST https://api.github.com/graphql`.
2. **Node IDs required for mutations.** Must resolve repo ID, category ID, label IDs before creating/modifying. The server handles this transparently.
3. **Labels cannot be set in `createDiscussion`.** The `CreateDiscussionInput` type has no `labelIds` field. Must use a separate `addLabelsToLabelable` mutation.
4. **Cannot filter discussions by label or author** in the `discussions()` query. Must use `search(type: DISCUSSION)` for those filters.
5. **Replies are one level deep.** `replyToId` must point to a top-level comment. Replies-to-replies are not supported.
6. **`discussion(number: N)` returns `null` for non-existent discussions** — no error is raised.
7. **Discussions must be enabled** on the repository (Settings → Features → Discussions). The tools should detect this gracefully.
8. **Mutations cost 5 points** vs. 1 for queries. Budget-conscious for bulk operations.
9. **Content-creating mutations** are limited to 80/minute and 500/hour (secondary limits). This applies across all GitHub content creation (issues, PRs, comments, discussions).

## Not in Scope

- Updating/deleting discussions (low priority for promotion use case; can add later)
- Marking comments as answers (only relevant for Q&A categories)
- Pinning/unpinning discussions (not supported via API)
- Discussion polls (not supported via API)
- Organization-level discussions (API is repository-scoped only)
- Reactions on discussions/comments

## Dependencies

- No new credentials — uses existing `GITHUB_TOKEN`
- No new MCP server process — extends existing `github` server
- New npm dependency: `@octokit/graphql` (likely already a transitive dependency of `@octokit/rest`)
- Discussions must be enabled on the target repository

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Discussions not enabled on repo | Tools return errors | Check `discussionCategories` first; return clear error message |
| GraphQL rate limit shared with REST tools | Heavy REST usage leaves less budget for discussions | Include `rateLimit` field in queries; warn when budget is low |
| Category names change | Cached category IDs become stale | Re-resolve on cache miss or mutation failure |
| Labels not settable at creation time | Two API calls instead of one; brief window where discussion exists without labels | Acceptable — labels appear within milliseconds of creation |

# Plan: GitHub Tools

**Status: Planned**

## Context

The agent can already interact with GitHub via the `bash` tool and the `gh` CLI, but this requires the agent to construct shell commands and parse unstructured output. Dedicated GitHub tools provide a structured, agent-friendly interface with proper input schemas, formatted output, and error handling — consistent with how Gmail, Calendar, and Contacts tools work.

## Authentication

**Personal Access Token (PAT)** — simplest option for a personal CLI agent.

| Option | Pros | Cons |
|--------|------|------|
| **Fine-Grained PAT** | Granular per-repo permissions, GitHub's recommended approach | Must expire (max 366 days), some features not yet supported (gists, notifications) |
| **Classic PAT** | Broad scope, covers all features, no required expiration | Coarser permissions |
| **GitHub App** | Short-lived tokens, higher rate limits | Complex setup (JWT, installation tokens), overkill for personal use |
| **OAuth App** | Standard web flow | Requires redirect/callback, not suitable for CLI |

**Decision:** Start with **Classic PAT** for simplicity and full feature coverage (`repo`, `workflow`, `notifications`, `gist` scopes). Switch to Fine-Grained PAT once it supports all needed features.

- Env var: `GITHUB_TOKEN` in `.env`
- No OAuth browser flow needed — just a static token
- Auth module creates a `githubkit` client with the token, cached as a module-level singleton (same pattern as Google auth modules)

## Python Library

| Library | Async | GraphQL | Typed | API Coverage | Maintenance |
|---------|:-----:|:-------:|:-----:|:------------:|:-----------:|
| **githubkit** | Yes | Yes | Full (Pydantic) | 100% (auto-generated) | Active |
| PyGithub | No | No | Partial | Good | Seeking maintainers |
| ghapi | No | Yes | Yes | 100% | Active |
| gidgethub | Yes | No | Limited | Manual | Active |
| Raw httpx | Yes | N/A | N/A | Manual | N/A |

**Decision:** `githubkit` — the only library offering async + GraphQL + full typing + auto-generated API coverage. Built on `httpx` (already a project dependency). Pin the version since it's pre-1.0.

**New dependency:** `githubkit[auth-app]` (or just `githubkit`)

## Rate Limits

| Category | Limit |
|----------|-------|
| REST API (authenticated) | 5,000 requests/hour |
| Search (repos/issues) | 30 requests/minute |
| **Search (code)** | **10 requests/minute** |
| GraphQL | 5,000 points/hour |
| Content creation | 80/minute, 500/hour |

The 5,000/hour REST limit is generous for interactive agent use. The **code search limit (10/min)** is the main constraint — tools should check `X-RateLimit-Remaining` headers and warn the user when approaching limits.

## Tools

### Phase 1: Core (highest value)

**`github_list_prs`** — List open PRs for a repo or across the user's repos.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | no | — | Repository (owner/repo). If omitted, lists across all user repos |
| `state` | string | no | `open` | Filter: `open`, `closed`, `all` |
| `author` | string | no | — | Filter by author username |
| `maxResults` | number | no | `10` | Max results (max 30) |

**`github_get_pr`** — Get detailed PR info including diff summary, reviews, and CI status.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | yes | — | Repository (owner/repo) |
| `number` | number | yes | — | PR number |

Output includes: title, body, author, branch, review status, CI check status, mergeable state, diff stats.

**`github_create_issue`** — Create a new issue.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | yes | — | Repository (owner/repo) |
| `title` | string | yes | — | Issue title |
| `body` | string | no | — | Issue body (markdown) |
| `labels` | array | no | `[]` | Label names to apply |
| `assignees` | array | no | `[]` | Usernames to assign |

**`github_list_issues`** — List/search issues.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | no | — | Repository (owner/repo). If omitted, lists across user's repos |
| `state` | string | no | `open` | Filter: `open`, `closed`, `all` |
| `labels` | string | no | — | Comma-separated label filter |
| `query` | string | no | — | Search query (uses GitHub search syntax) |
| `maxResults` | number | no | `10` | Max results (max 30) |

**`github_create_pr`** — Create a pull request.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | yes | — | Repository (owner/repo) |
| `title` | string | yes | — | PR title |
| `body` | string | no | — | PR description (markdown) |
| `head` | string | yes | — | Branch with changes |
| `base` | string | no | `main` | Branch to merge into |
| `draft` | boolean | no | `false` | Create as draft PR |

### Phase 2: Productivity

**`github_search_code`** — Search code across repositories.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | yes | — | Search query |
| `repo` | string | no | — | Limit to a specific repo (owner/repo) |
| `language` | string | no | — | Filter by language |
| `maxResults` | number | no | `10` | Max results (max 20) |

Note: Subject to the 10 requests/minute code search limit.

**`github_list_notifications`** — List unread notifications.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `all` | boolean | no | `false` | Include read notifications |
| `repo` | string | no | — | Filter by repo (owner/repo) |
| `maxResults` | number | no | `20` | Max results (max 50) |

**`github_list_workflow_runs`** — Check CI/CD status.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | yes | — | Repository (owner/repo) |
| `branch` | string | no | — | Filter by branch |
| `status` | string | no | — | Filter: `completed`, `in_progress`, `queued` |
| `maxResults` | number | no | `5` | Max results (max 20) |

### Phase 3: Nice to Have

**`github_add_comment`** — Comment on an issue or PR.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | yes | — | Repository (owner/repo) |
| `number` | number | yes | — | Issue or PR number |
| `body` | string | yes | — | Comment body (markdown) |

**`github_create_gist`** — Create a gist for quick code sharing.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `filename` | string | yes | — | File name (e.g. `snippet.py`) |
| `content` | string | yes | — | File content |
| `description` | string | no | — | Gist description |
| `public` | boolean | no | `false` | Public or secret gist |

## Implementation

### New Files

```
tools/
├── github/
│   ├── github_auth.py               # githubkit client (PAT, singleton)
│   ├── github_list_prs_tool.py
│   ├── github_get_pr_tool.py
│   ├── github_create_issue_tool.py
│   ├── github_list_issues_tool.py
│   ├── github_create_pr_tool.py
│   ├── github_search_code_tool.py
│   ├── github_list_notifications_tool.py
│   ├── github_list_workflow_runs_tool.py
│   ├── github_add_comment_tool.py
│   └── github_create_gist_tool.py
```

### Auth Module Pattern

```python
# github_auth.py
from githubkit import GitHub

_client: GitHub | None = None

async def get_github_client(token: str) -> GitHub:
    global _client
    if _client is not None:
        return _client
    _client = GitHub(token)
    return _client
```

No browser OAuth flow needed — just a token.

### Registration

Add `GITHUB_TOKEN` to `__main__.py` env var loading and `tool_registry.py`:

```python
# tool_registry.py
if github_token:
    from .tools.github.github_list_prs_tool import GitHubListPRsTool
    from .tools.github.github_get_pr_tool import GitHubGetPRTool
    from .tools.github.github_create_issue_tool import GitHubCreateIssueTool
    from .tools.github.github_list_issues_tool import GitHubListIssuesTool
    from .tools.github.github_create_pr_tool import GitHubCreatePRTool
    # ... etc

    tools.extend([
        GitHubListPRsTool(github_token),
        GitHubGetPRTool(github_token),
        GitHubCreateIssueTool(github_token),
        GitHubListIssuesTool(github_token),
        GitHubCreatePRTool(github_token),
    ])
```

### Output Formats

**PR list:**
```
Open PRs for octocat/hello-world: 2 results

1. #42 — Fix typo in README
   Author: octocat | Branch: fix-typo -> main
   Updated: 2026-02-18 | Reviews: 1 approved, 0 changes requested
   CI: passing

2. #38 — Add dark mode support
   Author: octocat | Branch: dark-mode -> main
   Updated: 2026-02-15 | Reviews: 0 approved, 1 changes requested
   CI: failing
```

**Issue list:**
```
Open issues for octocat/hello-world: 3 results

1. #55 — Login fails on mobile Safari [bug, high-priority]
   Author: jdoe | Created: 2026-02-17 | Comments: 4

2. #52 — Add export to CSV feature [enhancement]
   Author: octocat | Created: 2026-02-10 | Comments: 1
```

**Workflow runs:**
```
Recent workflow runs for octocat/hello-world: 3 results

1. CI Tests — #891 (main)
   Status: completed | Conclusion: success
   Triggered: 2026-02-18 14:30 | Duration: 3m 42s

2. CI Tests — #890 (dark-mode)
   Status: completed | Conclusion: failure
   Triggered: 2026-02-18 12:15 | Duration: 2m 18s
```

## Dependencies

- **New package:** `githubkit` (pin version in `pyproject.toml`)
- **New env var:** `GITHUB_TOKEN` (Classic PAT with `repo`, `workflow`, `notifications`, `gist` scopes)

## Not in Scope

- **Repository creation/deletion** — high-risk operations, use `gh` CLI
- **Branch management** — use `git` CLI directly
- **GitHub Pages** — niche feature
- **Organization/team management** — admin operations
- **Webhook management** — infrastructure concern
- **GraphQL custom queries** — use REST for simplicity in Phase 1; consider GraphQL for `github_get_pr` if REST requires too many calls
- **Rate limit dashboard tool** — check headers in individual tools instead

## Relationship to `gh` CLI

The `gh` CLI remains available via the `bash` tool as a fallback for operations not covered by dedicated tools. The dedicated tools provide:
- Structured input schemas (the LLM knows exactly what parameters to provide)
- Consistent output formatting (easier for the LLM to parse and summarize)
- Error handling and rate limit awareness
- No shell escaping issues

## Verification

1. **List PRs**: `github_list_prs` with a repo → returns formatted PR list
2. **Get PR detail**: `github_get_pr` on a known PR → returns diff stats, reviews, CI status
3. **Create issue**: `github_create_issue` → issue appears on GitHub
4. **Search issues**: `github_list_issues` with a query → returns matching issues
5. **Create PR**: `github_create_pr` from a branch → PR created on GitHub
6. **Notifications**: `github_list_notifications` → returns unread notifications
7. **Workflow runs**: `github_list_workflow_runs` → returns recent CI runs
8. **Tools registered**: GitHub tools appear in startup banner when `GITHUB_TOKEN` is set
9. **Rate limiting**: Hit the search API repeatedly → tool returns rate limit warning instead of error

# Design: Account Management APIs for Agent Integration

## Status

**Partially Implemented** — API surface inventory for Anthropic, OpenAI, and Claude Code management. The `anthropic_usage` tool (covering usage, cost, and Claude Code analytics endpoints) has been implemented. See [tool docs](tools/anthropic-usage/README.md).

## Problem

The assistant agent currently has no ability to interact with the management planes of the services it depends on. To enable self-service operations like checking usage, managing API keys, viewing costs, and administering organization members, we need to understand what administrative APIs each provider exposes and how the agent could call them.

This document catalogs the available APIs across three surfaces:

1. **Anthropic Admin API** — organization/workspace/key management for Claude API
2. **OpenAI Administration API** — organization/project/key management for OpenAI API
3. **Claude Code** — CLI/SDK programmatic interfaces and configuration management

---

## 1. Anthropic Admin API

### Overview

The Anthropic Admin API provides programmatic control over organization-level administrative tasks. It is **unavailable for individual accounts** — requires an organization set up in Console.

### Authentication

- **Key prefix:** `sk-ant-admin...` (distinct from standard API keys)
- **Header:** `x-api-key: <ADMIN_API_KEY>`
- **Version header:** `anthropic-version: 2023-06-01` (required)
- **Created by:** Organization admins only, via Console `/settings/admin-keys`

### Base URL

```
https://api.anthropic.com
```

### Endpoints

#### Organization

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/organizations/me` | Get organization info |

#### Members

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/organizations/users` | List members |
| `GET` | `/v1/organizations/users/{user_id}` | Get member |
| `POST` | `/v1/organizations/users/{user_id}` | Update role |
| `DELETE` | `/v1/organizations/users/{user_id}` | Remove member |

Roles: `user`, `developer`, `billing`, `claude_code_user`, `managed`, `admin` (admin cannot be set/removed via API).

#### Invites

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/organizations/invites` | Create invite |
| `GET` | `/v1/organizations/invites` | List invites |
| `GET` | `/v1/organizations/invites/{invite_id}` | Get invite |
| `DELETE` | `/v1/organizations/invites/{invite_id}` | Delete invite |

Invites expire after 21 days (not configurable).

#### Workspaces

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/organizations/workspaces` | Create workspace |
| `GET` | `/v1/organizations/workspaces` | List workspaces |
| `GET` | `/v1/organizations/workspaces/{workspace_id}` | Get workspace |
| `POST` | `/v1/organizations/workspaces/{workspace_id}` | Update workspace |
| `POST` | `/v1/organizations/workspaces/{workspace_id}/archive` | Archive workspace |

Max 100 workspaces per org. Default workspace cannot be edited/removed.

#### Workspace Members

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/organizations/workspaces/{id}/members` | Add member |
| `GET` | `/v1/organizations/workspaces/{id}/members` | List members |
| `POST` | `/v1/organizations/workspaces/{id}/members/{user_id}` | Update role |
| `DELETE` | `/v1/organizations/workspaces/{id}/members/{user_id}` | Remove member |

Workspace roles: `workspace_user`, `workspace_developer`, `workspace_admin`, `workspace_billing` (inherited).

#### API Keys

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/organizations/api_keys` | List keys |
| `GET` | `/v1/organizations/api_keys/{api_key_id}` | Get key |
| `POST` | `/v1/organizations/api_keys/{api_key_id}` | Update key (rename, activate, deactivate, archive) |

**Cannot create new keys via API** — Console only.

#### Usage Report

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/organizations/usage_report/messages` | Token-level usage data |

Supports `bucket_width` of `1m`, `1h`, `1d`. Group by `api_key_id`, `workspace_id`, `model`, `service_tier`, etc. Data freshness ~5 minutes.

#### Cost Report

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/organizations/cost_report` | Cost breakdown in USD |

Only `1d` bucket width. Returns amounts in cents. Priority Tier costs are excluded.

#### Claude Code Analytics

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/organizations/usage_report/claude_code` | Productivity metrics |

Per-user, per-day records: sessions, LOC added/removed, commits, PRs, tool acceptance rates, token usage by model, estimated cost. Data freshness ~1 hour.

### Pagination

Cursor-based: `limit` (1–1000, default 20), `after_id`, `before_id` for entity lists; `limit`, `page` for reports. Response includes `has_more`.

### Not Available via API

- Creating new API keys (Console only)
- Billing/payment management
- Rate limit configuration (tier-based)
- Promoting/removing admin role (Console only)

---

## 2. OpenAI Administration API

### Overview

OpenAI provides a comprehensive admin API covering projects, members, keys, RBAC, audit logs, usage, costs, and mTLS certificates.

### Authentication

- **Key type:** Admin API Key (separate from project API keys)
- **Header:** `Authorization: Bearer $OPENAI_ADMIN_KEY`
- **Created by:** Organization Owners only, via dashboard
- Admin keys **cannot** call inference endpoints; project keys **cannot** call admin endpoints.

### Base URL

```
https://api.openai.com/v1/organization/
```

### Endpoints

#### Admin API Keys

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/organization/admin_api_keys` | List admin keys |
| `POST` | `/organization/admin_api_keys` | Create admin key |
| `GET` | `/organization/admin_api_keys/{key_id}` | Get admin key |
| `DELETE` | `/organization/admin_api_keys/{key_id}` | Delete admin key |

#### Projects

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/organization/projects` | List projects |
| `POST` | `/organization/projects` | Create project |
| `GET` | `/organization/projects/{id}` | Get project |
| `POST` | `/organization/projects/{id}` | Modify project |
| `POST` | `/organization/projects/{id}/archive` | Archive project |

Projects can be archived but **not deleted**. Default project cannot be archived.

#### Project API Keys

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/organization/projects/{id}/api_keys` | List project keys |
| `GET` | `/organization/projects/{id}/api_keys/{key_id}` | Get project key |
| `DELETE` | `/organization/projects/{id}/api_keys/{key_id}` | Delete project key |

**Cannot create project keys via API** — users self-generate.

#### Project Users

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/organization/projects/{id}/users` | List users |
| `POST` | `/organization/projects/{id}/users` | Add user |
| `GET` | `/organization/projects/{id}/users/{user_id}` | Get user |
| `POST` | `/organization/projects/{id}/users/{user_id}` | Update role |
| `DELETE` | `/organization/projects/{id}/users/{user_id}` | Remove user |

#### Project Service Accounts

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/organization/projects/{id}/service_accounts` | List service accounts |
| `POST` | `/organization/projects/{id}/service_accounts` | Create (returns API key) |
| `GET` | `/organization/projects/{id}/service_accounts/{sa_id}` | Get service account |
| `DELETE` | `/organization/projects/{id}/service_accounts/{sa_id}` | Delete service account |

#### Project Rate Limits

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/organization/projects/{id}/rate_limits` | List rate limits |
| `POST` | `/organization/projects/{id}/rate_limits/{rl_id}` | Update rate limit |

Project limits cannot exceed organization limits. Fields: `max_requests_per_1_minute`, `max_tokens_per_1_minute`, `max_images_per_1_minute`.

#### Organization Users

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/organization/users` | List users |
| `GET` | `/organization/users/{user_id}` | Get user |
| `POST` | `/organization/users/{user_id}` | Update user |
| `DELETE` | `/organization/users/{user_id}` | Remove user |

#### Invites

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/organization/invites` | List invites |
| `POST` | `/organization/invites` | Create invite |
| `GET` | `/organization/invites/{invite_id}` | Get invite |
| `DELETE` | `/organization/invites/{invite_id}` | Delete invite |

#### Roles (RBAC)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/organization/roles` | List roles |
| `GET` | `/organization/roles/{role_id}` | Get role |
| `POST` | `/organization/roles/{role_id}` | Update role |

Granular permissions like `api.models.request`, `api.files.write`, etc.

#### Role Assignments

| Method | Path | Description |
|--------|------|-------------|
| `GET/POST` | `/organization/groups/{group_id}/roles` | Org-level group roles |
| `GET/POST` | `/organization/projects/{id}/groups/{group_id}/roles` | Project-level group roles |
| `POST` | `/organization/projects/{id}/users/{user_id}/roles` | Assign project role to user |

#### Audit Logs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/organization/audit_logs` | List audit events (51+ event types) |

Filterable by `effective_at`, `event_types[]`, `actor_emails[]`, `actor_ids[]`. Must be enabled by org owner.

#### Usage

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/organization/usage/completions` | Completions usage |
| `GET` | `/organization/usage/embeddings` | Embeddings usage |
| `GET` | `/organization/usage/images` | Image generation usage |
| `GET` | `/organization/usage/audio/speeches` | TTS usage |
| `GET` | `/organization/usage/audio/transcriptions` | Transcription usage |
| `GET` | `/organization/usage/moderations` | Moderation usage |
| `GET` | `/organization/usage/vector_stores` | Vector store usage |
| `GET` | `/organization/usage/code_interpreter_sessions` | Code interpreter usage |

Supports `bucket_width` of `1m`, `1h`, `1d`. Group by `project_id`, `model`, `user_id`, `api_key_id`.

#### Costs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/organization/costs` | Cost breakdown |

Only `1d` granularity. Group by `project_id`, `line_item`.

#### Certificates (mTLS)

| Method | Path | Description |
|--------|------|-------------|
| `GET/POST` | `/organization/certificates` | List/upload certs |
| `GET/POST/DELETE` | `/organization/certificates/{id}` | Manage cert |
| `POST` | `/organization/certificates/{id}/activate` | Activate |
| `POST` | `/organization/certificates/{id}/deactivate` | Deactivate |

Max 50 certificates per org.

### Pagination

Cursor-based: `after`, `limit` (1–100, default 20). Response includes `has_more`.

---

## 3. Claude Code Programmatic Interfaces

### Overview

Claude Code does not expose a REST API for account management. It provides two programmatic interfaces for **running agents** and a file-based configuration system.

### CLI Headless Mode (`claude -p`)

Run Claude Code non-interactively from scripts and automation:

```bash
claude -p "your prompt" --output-format json --allowedTools "Bash,Read,Write"
```

Supports: structured JSON output, streaming, JSON schema enforcement, system prompt customization, session continuation (`--continue`, `--resume`).

### Claude Agent SDK

Available as Python (`pip install claude-agent-sdk`) and TypeScript (`npm install @anthropic-ai/claude-agent-sdk`). Provides the same tools and agent loop as Claude Code as a library. **Does not expose any account management capabilities.**

### Configuration File Hierarchy

Claude Code settings are JSON files managed directly on disk (highest to lowest precedence):

| File | Location | Scope |
|------|----------|-------|
| Managed settings | OS-specific system path | Enterprise IT-enforced |
| CLI arguments | Runtime | Per-invocation |
| Project local | `.claude/settings.local.json` | Personal, not committed |
| Project shared | `.claude/settings.json` | Team-shared, committed |
| User global | `~/.claude/settings.json` | Personal global |

Key settings: `permissions`, `model`, `env`, `sandbox`, `hooks`, `apiKeyHelper`, `availableModels`.

The `apiKeyHelper` setting enables dynamic key generation via external scripts, allowing integration with secret managers.

### Integration with Anthropic Admin API

Claude Code usage is trackable via the Admin API's Claude Code Analytics endpoint. Organization admins can:
- Track per-user sessions, LOC, commits, PRs, tool usage
- Monitor token consumption and estimated costs by model
- Enforce policies via managed settings files deployed by IT

---

## Comparison Matrix

| Capability | Anthropic Admin API | OpenAI Admin API | Claude Code |
|-----------|:-------------------:|:----------------:|:-----------:|
| List/manage API keys | Partial (no create) | Partial (no create for project keys) | N/A |
| Create admin keys | No (Console) | Yes | N/A |
| Organization info | Yes | Yes (via users/projects) | N/A |
| Member management | Yes | Yes | N/A |
| Invite management | Yes | Yes | N/A |
| Workspace/Project management | Yes | Yes | N/A |
| Role-based access control | Basic (6 roles) | Advanced (custom roles, permissions) | N/A |
| Service accounts | No | Yes | N/A |
| Rate limit management | No | Yes (project-scoped) | N/A |
| Usage reporting | Yes (single endpoint) | Yes (per-service endpoints) | Via Anthropic Admin API |
| Cost reporting | Yes | Yes | Via Anthropic Admin API |
| Audit logs | No | Yes (51+ event types) | N/A |
| mTLS certificates | No | Yes | N/A |
| Subscription/billing mgmt | No (Console only) | No (Dashboard only) | No |

## Agent Integration Considerations

### Authentication Architecture

Both providers use a dedicated admin key pattern separate from inference keys:
- **Anthropic:** `sk-ant-admin...` in `x-api-key` header
- **OpenAI:** Admin API key in `Authorization: Bearer` header

These keys should be stored securely (e.g., via `apiKeyHelper` or environment variables) and **never** in config files committed to source control.

### Candidate Tool Designs

Based on the API surfaces, candidate tools for the agent could include:

| Tool Name | Provider | Operations |
|-----------|----------|------------|
| `anthropic-usage` | Anthropic | Query usage/cost reports, Claude Code analytics |
| `anthropic-org` | Anthropic | List members, workspaces, API keys, invites |
| `openai-usage` | OpenAI | Query usage/cost by service type |
| `openai-org` | OpenAI | List members, projects, keys, service accounts |
| `openai-audit` | OpenAI | Query audit logs |
| `openai-rate-limits` | OpenAI | View/update project rate limits |

### Security Constraints

- Admin keys grant broad organizational access — the agent should operate with **read-only** access by default
- Write operations (role changes, invites, key deactivation) should require explicit user confirmation
- Neither API supports creating inference API keys programmatically (by design)
- Subscription and billing management is Console/Dashboard-only for both providers

### SDK Support

- **Anthropic:** Official SDKs do not cover Admin API. Use direct HTTP requests (or unofficial `anthropic-admin` PyPI package).
- **OpenAI:** The official Python SDK (`openai`) does not appear to cover admin endpoints. Use direct HTTP requests.

Both are straightforward REST APIs with JSON payloads, making them good candidates for simple `httpx`-based tool implementations.

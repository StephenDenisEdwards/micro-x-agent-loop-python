# ADR-007: Google Contacts as Built-in Tools

## Status

Accepted

## Context

The agent already has Gmail and Google Calendar as built-in tools using `google-api-python-client` with OAuth2 authentication. These follow a consistent pattern: a per-service auth module (token caching, OAuth browser flow), individual tool classes with `execute()` methods, and conditional registration in `tool_registry.py` when Google credentials are present.

The user needs to search, view, create, update, and delete Google Contacts from within the agent. Two approaches were considered:

1. **MCP server** — implement contacts access as an external MCP server (like WhatsApp), communicating over stdio.
2. **Built-in tools** — add contacts tools directly in the agent codebase, following the same pattern as Gmail and Calendar.

## Decision

Implement Google Contacts as built-in tools using the Google People API v1, following the identical patterns established by Gmail and Calendar.

Reasons:

- **No new dependencies.** `google-api-python-client` and `google-auth-oauthlib` are already in `pyproject.toml`. The People API is just another Google API service.
- **Consistent architecture.** Gmail and Calendar already proved this pattern works well — same auth module structure, same tool class structure, same registry registration. Adding a third Google service the same way keeps the codebase predictable.
- **No IPC overhead.** Built-in tools run in-process. An MCP server would add process management, stdio communication, and a separate build/run step for no architectural benefit — this is a first-party Google API, not a third-party service with its own toolchain (see ADR-006).
- **Shared OAuth infrastructure.** The auth module mirrors `calendar_auth.py` exactly, just with a different scope and token directory. A future consolidation into a single Google auth module would be straightforward.

The implementation consists of:

- `tools/contacts/contacts_auth.py` — OAuth2 with `https://www.googleapis.com/auth/contacts` scope, token cache at `.contacts-tokens/`
- `tools/contacts/contacts_formatter.py` — shared formatting helpers for summary and detail views
- Six tool classes: `contacts_search`, `contacts_list`, `contacts_get`, `contacts_create`, `contacts_update`, `contacts_delete`

**Prerequisite:** The People API must be enabled in the same Google Cloud project used for Gmail and Calendar.

## Consequences

**Easier:**

- Full CRUD on Google Contacts from natural language (search, list, get, create, update, delete)
- Same OAuth flow users are already familiar with from Gmail/Calendar — first use triggers a browser consent screen
- Etag-based concurrency control on updates prevents accidental overwrites
- No additional processes, config, or dependencies to manage

**Harder:**

- Users must enable the People API in their Google Cloud project (one-time setup)
- A separate OAuth consent flow is required for the contacts scope (separate token cache from Gmail/Calendar)
- Adding more Google APIs in the future will continue to duplicate the auth module pattern — a shared Google auth module may be worth extracting if a fourth service is added

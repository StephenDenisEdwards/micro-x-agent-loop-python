# Architecture Decision Records

We record significant architectural decisions using the [Nygard ADR format](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

## Template

```markdown
# ADR-XXX: Title

## Status
Proposed | Accepted | Deprecated | Superseded by ADR-YYY

## Context
What is the issue that we're seeing that is motivating this decision or change?

## Decision
What is the change that we're proposing and/or doing?

## Consequences
What becomes easier or more difficult to do because of this change?
```

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-001](ADR-001-python-dotenv-for-secrets.md) | python-dotenv for secrets management | Accepted |
| [ADR-002](ADR-002-tenacity-for-retry.md) | tenacity for API retry resilience | Accepted |
| [ADR-003](ADR-003-streaming-responses.md) | Streaming responses via SSE | Accepted |
| [ADR-004](ADR-004-raw-html-for-gmail.md) | Raw HTML for Gmail email content | Accepted |
| [ADR-005](ADR-005-mcp-for-external-tools.md) | MCP for external tool integration | Accepted |
| [ADR-006](ADR-006-separate-repos-for-third-party-mcp-servers.md) | Separate repos for third-party MCP servers | Accepted |
| [ADR-007](ADR-007-google-contacts-built-in-tools.md) | Google Contacts as built-in tools | Accepted |
| [ADR-008](ADR-008-github-built-in-tools-with-raw-httpx.md) | GitHub as built-in tools via raw httpx | Accepted |
| [ADR-009](ADR-009-sqlite-memory-sessions-and-file-checkpoints.md) | SQLite memory for sessions, events, and file checkpoints | Accepted |

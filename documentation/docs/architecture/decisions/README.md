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
| [ADR-010](ADR-010-multi-provider-llm-support.md) | Multi-provider LLM support (provider abstraction) | Accepted |
| [ADR-011](ADR-011-continuous-voice-mode-via-stt-mcp-sessions.md) | Continuous voice mode via STT MCP sessions | Accepted |
| [ADR-012](ADR-012-layered-cost-reduction.md) | Layered cost reduction architecture | Accepted |
| [ADR-013](ADR-013-tool-result-summarization-reliability.md) | Tool result summarization is fundamentally unreliable | Accepted |
| [ADR-014](ADR-014-mcp-unstructured-data-constraint.md) | Structured tool results with configurable LLM formatting | Accepted |
| [ADR-015](ADR-015-all-tools-as-typescript-mcp-servers.md) | All tools as TypeScript MCP servers | Accepted |
| [ADR-016](ADR-016-retry-resilience-for-mcp-servers-and-transport.md) | Retry/resilience for MCP servers and transport | Accepted |
| [ADR-017](ADR-017-ask-user-pseudo-tool-for-human-in-the-loop.md) | Ask user pseudo-tool for human-in-the-loop questioning | Accepted |
| [ADR-018](ADR-018-trigger-broker-subprocess-dispatch.md) | Trigger broker with subprocess dispatch | Accepted |
| [ADR-019](ADR-019-typescript-codegen-template.md) | TypeScript codegen template | Proposed |
| [ADR-020](ADR-020-semantic-model-routing.md) | Semantic model routing across providers | Accepted |
| [ADR-021](ADR-021-same-family-provider-fallback.md) | Same-family provider fallback | Accepted |

Here’s the “do this in production” checklist for MCP servers, distilled into best practice themes (with the spec/docs as the anchor).

## Tool contracts: be explicit and machine-checkable

* **Always provide `inputSchema`** (JSON Schema) that is *tight* (use `additionalProperties: false` where sensible). The tools spec is explicit that `inputSchema` must be valid JSON Schema. ([Model Context Protocol][1])
* **Provide `outputSchema` whenever you can**, and keep it stable. It’s optional in the spec, but it’s the difference between “LLM guesses the shape” and “clients can validate.” ([Model Context Protocol][1])
* **Return structured results as JSON content**, not JSON-as-string, when you expect downstream automation (and validate before returning).

## Security model: treat tools as arbitrary code execution

* Follow the spec’s stance: **tools are dangerous**; hosts should require **explicit user consent** before invoking tools, and tool descriptions/annotations are **untrusted** unless the server is trusted. ([Model Context Protocol][2])
* **Least privilege everywhere**: scope credentials per tool/purpose, restrict file paths, DB roles, API permissions, and avoid “god tokens.” (This shows up repeatedly in security guidance.) ([Model Context Protocol][3])
* **Authenticate properly for remote servers** (don’t run unauthenticated HTTP/SSE on a public network), and separate auth concerns cleanly (the spec direction is to treat MCP servers as resource servers). ([Descope][4])
* **Defend against tool poisoning / capability confusion**: if you support dynamic tool changes, ensure tool lists and notifications can’t be spoofed or cross-session mixed. The security best-practices doc calls this out as a real risk pattern. ([Model Context Protocol][3])
* Prefer **trusted servers/providers**; don’t assume anyone audits third-party MCP servers for you. ([Claude][5])

## Transport & runtime hygiene

* Use **stdio whenever possible** for local servers; it’s recommended in the transports spec. ([Model Context Protocol][6])
* **Never write to stdout in stdio mode** (it corrupts JSON-RPC). Log to **stderr** or a file. This is explicitly called out in the official “build server” docs and debugging guidance. ([Model Context Protocol][7])
* Make HTTP/SSE servers production-grade: timeouts, backpressure, rate limiting, per-session isolation, and sane limits on payload size.

## Observability and auditability

* Add **structured logs** (tool name, request id, latency, outcome) and **audit logs** for sensitive operations (file writes, deletions, external side effects). This is repeatedly emphasized in implementation guides and security writeups. ([Model Context Protocol][3])
* Emit **errors that are actionable**: distinguish validation failures vs upstream API failures vs permission failures.

## Determinism and “LLM-proofing” (important for your agent loop work)

* Assume the model will sometimes send weird args. Do **server-side validation** against `inputSchema` and reject fast. ([Model Context Protocol][1])
* If a tool calls an external API, **normalize** and **validate** the upstream JSON before returning it (map to DTOs, strip secrets, cap arrays, enforce types).
* Consider **idempotency keys** and **dry-run** tools for side-effectful actions (create/delete/send), so hosts can preview.

## Versioning and compatibility

* Version your server + tools (semver), and treat schema changes as breaking when they are. (Commonly recommended in production best-practice writeups.) ([The New Stack][8])

---
Here’s a solid “production-grade” best-practice set for building **both** (a) **local stdio** MCP servers and (b) **remote Streamable HTTP / SSE** MCP servers, using **TypeScript + .NET**, without painting yourself into a corner.

## 1) One core, two transports

**Best practice:** implement tools/resources/prompts once, then expose them through two thin adapters:

* **Core domain layer**: tool handlers, schema, validation, authZ checks, output normalization
* **Transport adapters**:

  * **stdio** (single client, local process)
  * **Streamable HTTP** (multi-client, concurrent, optionally SSE streaming) ([Model Context Protocol][1])

This makes behavior identical across local/remote, which matters for debugging and safety.

---

## 2) Strong schemas: input *and* output

MCP tool definitions are schema-driven; **tight JSON Schemas** are the main way clients/hosts know what’s expected. ([Model Context Protocol][2])

**Do:**

* Define **`inputSchema`** for every tool (strict: required fields, enums, bounds, `additionalProperties:false` where feasible).
* Define **`outputSchema`** for tools that return JSON (even though it’s not universally used by every host yet, it’s a major reliability win). ([Model Context Protocol][2])
* Return results as structured **JSON content**, not JSON-as-string (unless it’s meant for human reading).

**Server-side validation is non-negotiable**: validate inputs against `inputSchema`, and validate your own outputs against `outputSchema` before returning.

---

## 3) Treat tools as dangerous code

The spec/security guidance is blunt: tools extend capability and can be abused; hosts should treat tool metadata as untrusted, and implementations must defend against common agent/tool attack vectors. ([Model Context Protocol][3])

**Do:**

* **Least privilege** credentials (per tool/per capability).
* **Explicit allowlists** for file paths, commands, URLs, SQL tables, etc.
* **Redact secrets** in tool results/logs.
* **Defend against tool poisoning**: don’t let a tool’s description be “instructions”; keep descriptions factual. (Security guidance calls out these classes of risk; many external writeups use the same term.) ([Model Context Protocol][3])

---

## 4) STDIO pitfalls (local)

**Rule #1:** never write to **stdout** in stdio mode—stdout is the protocol channel; logging there corrupts JSON-RPC. Use stderr or file logging. ([Model Context Protocol][4])

**Do:**

* TS: log to `process.stderr` (or a logger configured to stderr).
* .NET: log via `ILogger` and ensure it targets stderr/file (not `Console.WriteLine`) for stdio. ([Model Context Protocol][4])
* Consider “capability minimization” for local servers: default read-only; require explicit config flags for write/delete.

---

## 5) Remote HTTP/SSE pitfalls (multi-tenant thinking)

Streamable HTTP servers can handle **multiple concurrent clients**, and may optionally stream server messages over SSE. ([Model Context Protocol][1])

**Do:**

* **Authentication + authorization** (don’t expose an unauthenticated MCP endpoint).
* **Per-session isolation**: don’t leak tool state/results across clients.
* **Rate limits + timeouts + payload limits** (tool calls can be abused).
* **Backpressure** for streaming: cap concurrent streams, cap token/bytes, kill stuck streams.
* **Idempotency keys** for side-effectful tools (email/send, payments, writes).

If you’re supporting SSE streaming, treat it like any other streaming API: disconnect handling, retry logic, and resource cleanup are part of “done”.

---

## 6) Normalize external API JSON before returning

When your tool wraps an upstream API:

* Validate upstream JSON → map to DTO → enforce output schema → return.
* Cap arrays/strings; strip unexpected fields.
* Never pass through secrets (headers, tokens, raw error bodies).

This prevents “upstream changed shape” from silently breaking downstream agents.

---

## 7) Observability you’ll actually use

**Do:**

* Structured logs: request id, tool name, duration, outcome.
* Audit log for side effects.
* Correlate: MCP request id ↔ your internal trace id.

This is especially important when you run the same server in stdio and HTTP mode.

---

## 8) Stack-specific notes

### TypeScript

Use the official TS SDK as the foundation (it includes server libs and both transports). ([GitHub][5])
Pattern:

* core tool implementations with zod/ajv validation
* adapter: stdio transport
* adapter: express/hono/Node HTTP transport (streamable HTTP + optional SSE)

### .NET

Microsoft has guidance + an official C# SDK repo; treat it as evolving, but it’s the right base. ([Microsoft for Developers][6])
Pattern:

* core: minimal API / service layer with DTO + JSON Schema validation
* adapter: stdio host (careful with stdout)
* adapter: ASP.NET Core endpoint for streamable HTTP (+ SSE if needed)

---

## A practical “golden path” architecture for you

Given you’re doing both TS and .NET, a common winning approach is:

* **TS for local developer-facing stdio servers** (fast iteration; easy packaging)
* **.NET for remote servers** where you want:

  * stronger typing/DTO discipline
  * enterprise hosting + auth + observability
  * robust concurrency

But keep the *contract* consistent: shared schemas (JSON Schema files in a repo) + conformance tests.

---

If you want, I can give you:

1. a **reference folder layout** that supports stdio + HTTP/SSE in the same codebase (TS and .NET), and
2. a **conformance test harness** that validates `tools/list` schemas and round-trips tool calls across both transports.

[1]: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports?utm_source=chatgpt.com "Transports"
[2]: https://modelcontextprotocol.io/specification/2025-06-18?utm_source=chatgpt.com "Specification"
[3]: https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices?utm_source=chatgpt.com "Security Best Practices"
[4]: https://modelcontextprotocol.io/docs/develop/build-server?utm_source=chatgpt.com "Build an MCP server"
[5]: https://github.com/modelcontextprotocol/typescript-sdk?utm_source=chatgpt.com "modelcontextprotocol/typescript-sdk"
[6]: https://devblogs.microsoft.com/dotnet/build-a-model-context-protocol-mcp-server-in-csharp/?utm_source=chatgpt.com "Build a Model Context Protocol (MCP) server in C# - .NET Blog"

---

[1]: https://modelcontextprotocol.io/specification/draft/server/tools?utm_source=chatgpt.com "Tools"
[2]: https://modelcontextprotocol.io/specification/2025-03-26?utm_source=chatgpt.com "Specification"
[3]: https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices?utm_source=chatgpt.com "Security Best Practices"
[4]: https://www.descope.com/blog/post/mcp-server-security-best-practices?utm_source=chatgpt.com "MCP Server Security Best Practices to Prevent Risk"
[5]: https://code.claude.com/docs/en/security?utm_source=chatgpt.com "Security - Claude Code Docs"
[6]: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports?utm_source=chatgpt.com "Transports"
[7]: https://modelcontextprotocol.io/docs/develop/build-server?utm_source=chatgpt.com "Build an MCP server"
[8]: https://thenewstack.io/15-best-practices-for-building-mcp-servers-in-production/?utm_source=chatgpt.com "15 Best Practices for Building MCP Servers in Production"

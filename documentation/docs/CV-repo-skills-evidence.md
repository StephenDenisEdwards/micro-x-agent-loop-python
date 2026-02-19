# CV Skills Evidence From Local Repositories

## Scope
Analysis source: local git repositories under `C:\Users\steph\source\repos`.

Repositories reviewed:
- `claude-agent-sdk-python` (Anthropic)
- `interview-assist-2` (StephenDenisEdwards)
- `mcp-servers` (StephenDenisEdwards)
- `micro-x-agent-loop` (StephenDenisEdwards)
- `micro-x-agent-loop-dotnet` (StephenDenisEdwards)
- `micro-x-agent-loop-python` (StephenDenisEdwards)
- `openclaw` (OpenClaw)
- `torch-playground` (StephenDenisEdwards)
- `whatsapp-mcp` (lharries)

Note: CV claims should prioritize repos owned by `StephenDenisEdwards`; external repos are strongest as "worked with/contributed to/evaluated" evidence unless you authored substantial changes there.

## Executive Profile (Draft)
Software engineer focused on AI agent systems, tool-enabled LLM workflows, and production-ready platform integration. Builds cross-language systems (Python, TypeScript/Node.js, C#/.NET, Go) with emphasis on streaming UX, reliable tool execution, memory/session management, and extensible gateway/MCP architectures. Experienced with real-time data pipelines, cloud/API integration, and quality engineering (tests, architecture docs, and operational runbooks).

## Skills Matrix
### Languages
- Python (agent runtime, tool orchestration, memory/session features)
- TypeScript/Node.js (agent loop implementation, gateway patterns)
- C#/.NET (agent runtime, MCP servers, real-time console tooling)
- Go (WhatsApp bridge and service integration exposure)
- SQL/SQLite (local persistence for session and message storage)

### AI/LLM Engineering
- Agent loop design (REPL-driven autonomous workflows)
- Tool-calling orchestration and parallel tool execution
- Conversation compaction/summarization for context window management
- Session memory and checkpoint concepts for long-running agents
- Multi-provider integration patterns (Anthropic, OpenAI in adjacent ecosystem)
- Prompt and operational safety awareness (prompt injection/exfiltration risks)

### Integration & Protocols
- Model Context Protocol (MCP): server/client integration patterns
- Google integrations: Gmail/Calendar/Contacts OAuth tool flows
- Web integrations: search/fetch tools and content retrieval pipelines
- Messaging integrations: WhatsApp-centric MCP patterns; OpenClaw multi-channel architecture exposure

### Platform & Runtime
- .NET 8/10, Python 3.11+, Node 20/22+
- Async/concurrency patterns (`asyncio`, parallel tool execution, .NET async)
- Resilience patterns (retry/backoff; Polly/Tenacity)
- Structured logging and diagnostics

### DevOps & Engineering Practice
- GitHub-based multi-repo delivery
- Docker exposure (notably in OpenClaw ecosystem)
- Test suites across Python and .NET projects
- Architecture artifacts: SAD, ADRs, design docs, planning docs, troubleshooting guides

## Project Evidence By Repository
### `micro-x-agent-loop-python`
- Python AI agent loop with streaming responses, tool execution, compaction, and MCP integration.
- Built-in integrations include file, shell, Gmail, Calendar, Contacts, GitHub, web search/fetch, and LinkedIn job tools.
- Recent architecture/documentation maturity visible via SAD/ADR/design and planning docs.
- Strong evidence for: Python agent engineering, modular tool systems, and maintainable architecture.

### `micro-x-agent-loop-dotnet`
- .NET-based implementation of the same agent-loop model.
- Evidence of parallel tool execution, retry policies, conditional tool registration, structured logging, and MCP connectivity.
- Strong evidence for: C#/.NET production architecture and parity implementation across languages.

### `micro-x-agent-loop` (TypeScript)
- TypeScript/Node baseline implementation evolving toward full assistant capability.
- Evidence for: Node runtime agent patterns, extensibility planning, and cross-platform intent.

### `interview-assist-2`
- Real-time interview assistant with audio capture, transcription, and LLM intent detection.
- Multi-project .NET solution with playback, annotation, evaluation strategy, and tests.
- Strong evidence for: real-time processing, applied LLM classification, and product-oriented engineering.

### `mcp-servers`
- .NET MCP servers project (system info server currently visible).
- Strong evidence for: protocol-driven integration development and server-side tool exposure.

### `torch-playground`
- Small experimentation repo with Python artifacts.
- Evidence for: ML experimentation/prototyping mindset.

### `openclaw` (external repo in workspace)
- Large TypeScript-first personal assistant platform with gateway architecture, multi-channel messaging, and onboarding/operations tooling.
- Evidence for: understanding enterprise-scale agent platform patterns and deployment considerations.

### `whatsapp-mcp` (external repo in workspace)
- MCP server for WhatsApp including bridge and local storage model.
- Evidence for: practical messaging integration patterns, local-first data handling, and MCP ecosystem familiarity.

### `claude-agent-sdk-python` (external repo in workspace)
- SDK surface and usage patterns for Claude Agent integration in Python.
- Evidence for: familiarity with SDK-driven agent invocation and async message streaming APIs.

## CV-Ready Bullet Bank
Use/adapt these based on your exact contribution level.

- Designed and implemented multi-language AI agent runtimes (Python, .NET, TypeScript) with tool-calling, streaming responses, and context compaction.
- Built modular tool ecosystems integrating file/shell operations, Google Workspace APIs (Gmail/Calendar/Contacts), web retrieval, and GitHub workflows.
- Implemented/extensively used MCP-based architecture to discover and execute tools via external protocol-compliant servers.
- Developed resilient LLM orchestration using retry/backoff policies, configurable limits, and structured logging for operational reliability.
- Engineered real-time transcription and intent detection workflows in .NET, including playback/annotation and evaluation support for interview-assistance use cases.
- Produced architecture-level engineering documentation (SAD, ADRs, design specs, planning docs, troubleshooting guides) to improve maintainability and team onboarding.
- Evaluated and aligned local agent designs against OpenClaw-style gateway patterns and messaging-channel integration models.

## Suggested CV Skill Section (Condensed)
- Languages: Python, C#, TypeScript/JavaScript, Go (working), SQL
- AI/LLM: Agent loops, tool-calling, context compaction, session/memory concepts, prompt safety
- Frameworks/Protocols: .NET 8/10, Node.js, MCP, async/concurrent execution
- Integrations: Anthropic API, OpenAI-adjacent ecosystem, Gmail/Calendar/Contacts OAuth, GitHub APIs, web search/fetch
- Engineering: Architecture docs (SAD/ADR), test automation, logging/observability, cross-platform delivery

## Optional Positioning Statement For CV Summary
"Engineer specialized in practical AI agent platforms: I build tool-enabled, memory-aware assistants across Python/.NET/TypeScript, integrate real-world services via MCP and OAuth APIs, and harden systems with robust architecture, tests, and operational documentation."

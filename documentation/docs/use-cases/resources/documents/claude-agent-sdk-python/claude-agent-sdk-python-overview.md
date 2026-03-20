# Claude Agent SDK for Python: Codebase Overview

## 1. Purpose and Scope
The repository implements the `claude-agent-sdk` Python package, an async SDK for interacting with Claude Code through the Claude CLI. It supports two core usage patterns:

- `query()` for one-shot or unidirectional streaming workloads.
- `ClaudeSDKClient` for interactive, bidirectional sessions with runtime control.

The SDK wraps CLI transport details, parses streamed JSON messages into typed Python dataclasses, and exposes extension points for:

- Tool permission callbacks (`can_use_tool`)
- Hook callbacks (PreToolUse/PostToolUse/etc.)
- In-process SDK MCP servers (Python tool functions exposed to Claude)
- Dynamic control operations (interrupt, set model, set permission mode, rewind files)

## 2. Top-Level Repository Layout
- `src/claude_agent_sdk/`: package source code
- `tests/`: unit + mocked integration tests
- `e2e-tests/`: real API end-to-end tests (requires `ANTHROPIC_API_KEY`)
- `examples/`: runnable usage examples (query mode, streaming mode, hooks, MCP, options)
- `scripts/`: release/build/version automation scripts
- `.github/workflows/`: CI, lint, build, publish, auto-release workflows
- `pyproject.toml`: packaging/dependencies/tool config
- `README.md`: public usage docs
- `CHANGELOG.md`: release history

## 3. Public API Surface
Primary exports are assembled in `src/claude_agent_sdk/__init__.py`.

### Main entry points
- `query(...)` (`src/claude_agent_sdk/query.py`)
- `ClaudeSDKClient` (`src/claude_agent_sdk/client.py`)
- `Transport` abstract base class (`src/claude_agent_sdk/_internal/transport/__init__.py`)

### Core models and config
- `ClaudeAgentOptions` and many typed dataclasses/TypedDicts live in `src/claude_agent_sdk/types.py`.
- Message model includes: `UserMessage`, `AssistantMessage`, `SystemMessage`, `ResultMessage`, `StreamEvent`.
- Content blocks include: `TextBlock`, `ThinkingBlock`, `ToolUseBlock`, `ToolResultBlock`.

### Extension APIs
- `tool(...)` decorator + `create_sdk_mcp_server(...)` for in-process MCP tools.
- Hook callback types (`HookInput`, `HookJSONOutput`, `HookMatcher`, etc.).
- Permission callback types (`CanUseTool`, `PermissionResultAllow`, `PermissionResultDeny`, `PermissionUpdate`).

## 4. Architectural Overview
At a high level, the SDK layers are:

1. Public API layer: `query()` and `ClaudeSDKClient`
2. Internal orchestration layer: `InternalClient` + `Query`
3. I/O layer: `Transport` abstraction + `SubprocessCLITransport`
4. Parsing layer: `parse_message()` converts raw JSON into typed SDK messages

### 4.1 One-shot path (`query`)
- `query()` sets entrypoint env marker and delegates to `InternalClient.process_query(...)`.
- `InternalClient` validates option combinations, configures transport, starts the `Query` control layer, initializes it, writes user input (or streams iterable input), and yields parsed messages.

### 4.2 Interactive path (`ClaudeSDKClient`)
`ClaudeSDKClient` manages lifecycle and runtime controls:
- `connect(...)` to initialize transport + control protocol
- `query(...)` to send user messages
- `receive_messages()` / `receive_response()` to stream parsed output
- control methods: `interrupt()`, `set_permission_mode()`, `set_model()`, `rewind_files()`, `get_mcp_status()`, `get_server_info()`
- context-manager support (`async with ClaudeSDKClient(...)`)

## 5. Transport and Process Management
`src/claude_agent_sdk/_internal/transport/subprocess_cli.py` is the key infrastructure component.

### Responsibilities
- Find CLI binary (bundled first, fallback to PATH/common locations)
- Build CLI command from `ClaudeAgentOptions`
- Spawn and manage subprocess using `anyio.open_process`
- Serialize writes to stdin with a lock (`_write_lock`) to prevent concurrent write races
- Read stdout as streaming JSON with buffering/reassembly logic
- Optionally pipe stderr to callback (`options.stderr`) or legacy debug stream
- Enforce max buffer size for partial JSON accumulation

### Important behavior
- Internally always uses stream-json input mode.
- Agent configs are sent during initialize control request (not CLI args), avoiding command-line length limits.
- Supports merged settings behavior for sandbox + settings JSON/path.

## 6. Control Protocol Layer (`Query`)
`src/claude_agent_sdk/_internal/query.py` coordinates bidirectional control messages:

- Sends `initialize` request and caches initialization result.
- Handles CLI `control_request` messages for:
  - tool permission callback (`can_use_tool`)
  - hook callback execution
  - SDK MCP message routing
- Sends control responses and maps pending control request IDs to events/results.
- Routes non-control messages to downstream consumers.
- Supports outgoing control commands (`interrupt`, `set_permission_mode`, `set_model`, `rewind_files`, `mcp_status`).

### Hook field conversion
Python-safe keys (`async_`, `continue_`) are converted to CLI keys (`async`, `continue`) before sending responses.

## 7. Message Parsing and Typing
`src/claude_agent_sdk/_internal/message_parser.py` performs strict-ish parsing into typed dataclasses.

Supported raw message types:
- `user`
- `assistant`
- `system`
- `result`
- `stream_event`

Invalid formats raise `MessageParseError` with source data attached.

## 8. In-Process SDK MCP Server Support
Implemented in `src/claude_agent_sdk/__init__.py` + control routing in `Query._handle_sdk_mcp_request(...)`.

### Developer-facing API
- Define tools using `@tool(name, description, input_schema, annotations=...)`
- Compose server via `create_sdk_mcp_server(name, version, tools=[...])`
- Pass in `ClaudeAgentOptions(mcp_servers={...})`

### Runtime model
- SDK MCP servers run in-process (no separate subprocess for tool server).
- Query bridges JSON-RPC-like MCP calls from CLI to registered Python MCP handlers.
- Current implementation manually routes key methods (`initialize`, `tools/list`, `tools/call`, `notifications/initialized`).

## 9. Configuration Model (`ClaudeAgentOptions`)
`ClaudeAgentOptions` is the central config dataclass with a broad set of options:

- Tool policy: `tools`, `allowed_tools`, `disallowed_tools`, `permission_mode`
- Prompt/model: `system_prompt`, `model`, `fallback_model`, `max_turns`, `max_budget_usd`
- Context/session: `cwd`, `continue_conversation`, `resume`, `fork_session`
- Advanced protocol: `include_partial_messages`, `can_use_tool`, `hooks`, `agents`
- MCP/plugin: `mcp_servers`, `plugins`
- Runtime/env: `env`, `user`, `extra_args`, `stderr`
- Structured output/thinking: `output_format`, `thinking`, `effort`, `max_thinking_tokens`
- File checkpoints: `enable_file_checkpointing`
- Settings/sandbox: `settings`, `setting_sources`, `sandbox`, `add_dirs`

## 10. Error Model
Defined in `src/claude_agent_sdk/_errors.py`:

- `ClaudeSDKError` base
- `CLIConnectionError`
- `CLINotFoundError`
- `ProcessError`
- `CLIJSONDecodeError`
- `MessageParseError`

These errors isolate process startup issues, CLI absence, stream decode failures, and parse failures.

## 11. Test Suite Overview

### 11.1 Unit and mocked integration tests (`tests/`)
Coverage includes:
- Transport command construction and process lifecycle
- Concurrency safeguards on writes
- Stream buffering edge cases (split JSON, multiple JSON in one read, max buffer)
- Message parsing correctness and parse error behavior
- Tool permission and hook callback protocol behavior
- SDK MCP server registration and tool execution behavior
- Client/query behavior for connection lifecycle, send/receive, interrupt, etc.
- Changelog format/order checks

Notable point: There is no `tests/test_query.py`; query behavior is tested in other files (for example `tests/test_client.py`).

### 11.2 E2E tests (`e2e-tests/`)
These run against real Claude API and validate:
- Hooks behavior end-to-end
- Dynamic control (`set_permission_mode`, `set_model`, `interrupt`)
- Agents and settings sources behavior (including large agent definitions)
- Partial message streaming (`StreamEvent`)
- SDK MCP tool execution and permission enforcement
- Structured output via JSON schema
- `stderr` callback behavior
- Permission callback invocation for non-read-only tools

Requires `ANTHROPIC_API_KEY`.

## 12. CI/CD and Release Pipeline

### CI workflows
- `test.yml`: multi-OS unit tests + e2e + docker e2e + example runs
- `lint.yml`: ruff + mypy

### Publish workflows
- `publish.yml` and reusable `build-and-publish.yml`:
  - Build platform-specific wheels with bundled CLI
  - Build sdist
  - Publish artifacts to PyPI
  - Update version files and changelog flow

### Auto-release
- `auto-release.yml` can trigger SDK patch release when bundled CLI version is bumped.

## 13. Packaging and Versioning
From `pyproject.toml` and version files:
- Package: `claude-agent-sdk`
- Current SDK version: `0.1.37` (`src/claude_agent_sdk/_version.py`)
- Bundled CLI version: `2.1.45` (`src/claude_agent_sdk/_cli_version.py`)
- Python: `>=3.10`
- Main deps: `anyio`, `mcp`, `typing_extensions` (for older Python)

Build tooling uses `hatchling`.

## 14. Design Characteristics and Tradeoffs

### Strengths
- Clear separation between public API, transport, control protocol, and parsing
- Strong type surface for options/messages/hooks
- Good callback extensibility (hooks, permission callbacks, MCP)
- Robust transport tests around race conditions and buffering
- Real e2e coverage for high-risk integration paths

### Tradeoffs / constraints
- CLI-centric architecture means runtime behavior depends on external CLI compatibility.
- SDK MCP routing currently manually handles specific MCP methods (not fully generic transport adapter).
- Some behavior relies on environment flags and CLI semantics that can evolve.

## 15. Typical Runtime Flow (End-to-End)
1. Caller invokes `query(...)` or `ClaudeSDKClient.connect(...)`.
2. SDK resolves options and starts subprocess transport.
3. `Query.start()` begins asynchronous message reader.
4. `Query.initialize()` sends hook/agent config through control protocol.
5. User messages stream to CLI stdin as JSON lines.
6. CLI emits mixed stream of control + SDK messages.
7. Control messages are handled internally; SDK messages are parsed and yielded.
8. Conversation ends on `ResultMessage` (for `receive_response`) or full stream close.
9. Client/query closes transport and task resources.

## 16. Practical Entry Points for Contributors
For targeted changes, start here:

- Public behavior changes: `src/claude_agent_sdk/client.py`, `src/claude_agent_sdk/query.py`
- Option-to-CLI mapping: `src/claude_agent_sdk/_internal/transport/subprocess_cli.py`
- Control protocol semantics: `src/claude_agent_sdk/_internal/query.py`
- Message object mapping: `src/claude_agent_sdk/_internal/message_parser.py`
- API surface/types: `src/claude_agent_sdk/types.py`, `src/claude_agent_sdk/__init__.py`
- Regression safety: corresponding `tests/` + `e2e-tests/`

## 17. Summary
This codebase is a production-oriented Python SDK that wraps Claude Code CLI with typed async interfaces and extensibility features. Its architecture is centered on a robust transport and control-protocol core, with significant test coverage across both mocked and real API scenarios, plus release automation for bundling CLI binaries into distributable wheels.

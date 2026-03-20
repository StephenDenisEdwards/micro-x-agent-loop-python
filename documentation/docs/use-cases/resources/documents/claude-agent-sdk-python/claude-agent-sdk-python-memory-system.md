# Claude Agent SDK Python: Memory System (Detailed Technical Overview)

## 1. Executive Summary
The SDK does not implement a standalone long-term memory engine (for example, no vector store, retrieval index, or embedding cache in this repo). Instead, it implements a **session-oriented memory control layer** on top of Claude Code CLI.

In practical terms, memory is implemented through:

- Conversation/session identity (`session_id`, `continue_conversation`, `resume`, `fork_session`)
- Message replay artifacts (`UserMessage.uuid`, `tool_use_result` metadata)
- File-state checkpointing and rewind (`enable_file_checkpointing`, `rewind_files(...)`)
- Incremental response state streaming (`include_partial_messages` + `StreamEvent`)
- Hook and permission context propagation (`HookInput`, `ToolPermissionContext`)
- In-process runtime buffers used for coordination (`Query` memory object stream, pending control maps)

Core point: the SDK controls, routes, and exposes memory state; the canonical persistent conversation memory lives in Claude Code/session infrastructure behind the CLI.

## 2. Memory Model by Layer

### 2.1 User-visible memory domains
1. Conversation memory
- Maintained by session identity and CLI-side session state.
- Exposed through session options and session IDs in messages.

2. File-change memory
- Optional checkpoint tracking during a session.
- Allows rewinding filesystem edits to a prior user-message checkpoint.

3. Streaming generation memory
- Partial token/event stream represented as typed `StreamEvent` objects.
- Supports real-time UIs and incremental state handling.

4. Hook/permission context memory
- Per-event contextual payloads (tool input, transcript path, session, cwd, suggestions).
- Allows deterministic policy and enrichment logic.

### 2.2 Internal runtime memory domains
1. Transport output reassembly buffer (`json_buffer`) in `SubprocessCLITransport`.
2. In-memory async message queue in `Query`.
3. Pending control-request synchronization maps in `Query`.
4. Callback registry for dynamic hook callback dispatch in `Query`.

These are ephemeral process memory structures, not persisted across runs.

## 3. Public API Surface for Memory Semantics
Memory-relevant fields/methods are primarily in `src/claude_agent_sdk/types.py` and `src/claude_agent_sdk/client.py`.

### 3.1 Session continuity controls (`ClaudeAgentOptions`)
- `continue_conversation: bool`
- `resume: str | None`
- `fork_session: bool`
- `setting_sources: list["user"|"project"|"local"] | None` (indirectly affects loaded context/settings)

### 3.2 File checkpoint controls
- `enable_file_checkpointing: bool` in `ClaudeAgentOptions`
- `ClaudeSDKClient.rewind_files(user_message_id: str)`

### 3.3 Message-level identifiers and replay metadata
`UserMessage` contains:
- `uuid: str | None` (checkpoint anchor)
- `tool_use_result: dict[str, Any] | None` (includes edit metadata such as structured patch details)

`ResultMessage` contains:
- `session_id: str` (conversation identity emitted by backend)

`StreamEvent` contains:
- `uuid: str`
- `session_id: str`
- `event: dict[str, Any]` (raw stream delta/event)

### 3.4 Streaming memory toggle
- `include_partial_messages: bool` in `ClaudeAgentOptions`
- Emits interleaved `StreamEvent` objects in response stream when enabled.

## 4. CLI Mapping: Where Memory Options Become Runtime Behavior
The SDK converts memory controls into CLI flags/environment in `src/claude_agent_sdk/_internal/transport/subprocess_cli.py`.

Memory-relevant mappings:
- `continue_conversation=True` -> `--continue`
- `resume="..."` -> `--resume <id>`
- `fork_session=True` -> `--fork-session`
- `include_partial_messages=True` -> `--include-partial-messages`
- `enable_file_checkpointing=True` -> env var `CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING=true`

Implication: SDK memory features are partly protocol-level and partly delegated to CLI runtime capabilities.

## 5. Conversation Memory Lifecycle

### 5.1 Establishing memory context
- `ClaudeSDKClient.connect(...)` initializes transport and control channel.
- `Query.initialize()` sends initialize request and receives server init payload.
- Each query message carries `session_id`.

### 5.2 Session identity behavior
In `ClaudeSDKClient.query(...)`:
- Default `session_id="default"` for string prompts.
- For async iterable prompts, SDK injects `session_id` when absent.

In `query(...)` one-shot path (`InternalClient.process_query`):
- For string prompts, SDK writes a user message with empty `session_id` (`""`), leaving backend/session behavior to CLI.

### 5.3 Continuation/resume/fork semantics
- `continue_conversation` requests continuation mode.
- `resume` attaches to a prior session identifier.
- `fork_session` asks backend to branch to new session identity while inheriting history context.

Memory interpretation:
- This is not local Python-side transcript persistence.
- It is **remote session memory addressing** through CLI flags and backend session manager.

## 6. File Checkpointing and Rewind Memory

### 6.1 Activation
Set:
- `ClaudeAgentOptions(enable_file_checkpointing=True)`

SDK sets environment marker for CLI process to enable checkpoint tracking.

### 6.2 Capturing checkpoint IDs
To rewind to a specific point, app needs user-message UUIDs.
- `UserMessage.uuid` is parsed and exposed by message parser.
- Documentation in `client.py` indicates use with `extra_args={"replay-user-messages": None}` to receive replayed user message UUIDs in stream.

### 6.3 Rewind protocol
`ClaudeSDKClient.rewind_files(user_message_id)` delegates to `Query.rewind_files(...)`, which sends control request:
- `{ "subtype": "rewind_files", "user_message_id": ... }`

This asks CLI/backend to restore tracked files to state at that checkpoint.

### 6.4 What this is and is not
Is:
- Versioned file-state memory within an active/managed session context.

Is not:
- Generic application object-store rollback.
- SDK-side git-like version store.

## 7. Streaming Event Memory (Partial Messages)

### 7.1 Mechanism
With `include_partial_messages=True`, backend emits `stream_event` payloads, parsed into `StreamEvent` dataclasses.

### 7.2 State utility
Enables UI/state machines to:
- Track message construction incrementally (`content_block_delta`, etc.)
- Build low-latency displays
- Observe thinking deltas and tool progress before final assistant/result message

### 7.3 Coexistence with final messages
Stream events are interleaved with `SystemMessage`, `AssistantMessage`, and `ResultMessage`. They complement final memory state; they do not replace final canonical message objects.

## 8. Hook and Permission Context as Operational Memory

### 8.1 Hook input memory payload
`HookInput` types include:
- `session_id`
- `transcript_path`
- `cwd`
- tool identifiers and tool inputs (event dependent)

This gives callback logic access to active conversational and execution context.

### 8.2 Permission callback memory payload
`ToolPermissionContext` includes:
- `suggestions` (permission update suggestions from CLI)
- placeholder signal field

This allows policy code to evaluate current execution context and optionally return permission updates targeted by destination, including `session`.

### 8.3 Additional context writes
Hook outputs can include `additionalContext` and hook-specific decisions, effectively writing control/context feedback back into the running agent loop.

## 9. Internal Runtime Memory Structures
Implemented in `src/claude_agent_sdk/_internal/query.py`.

### 9.1 Message queue
- `anyio.create_memory_object_stream(max_buffer_size=100)`
- Holds parsed raw SDK messages after control routing.
- Bounded queue protects against unbounded in-process growth.

### 9.2 Pending control-request state
- `pending_control_responses: dict[request_id, Event]`
- `pending_control_results: dict[request_id, result|Exception]`

This is short-lived correlation memory for request/response synchronization.

### 9.3 Hook callback registry
- `hook_callbacks: dict[callback_id, callable]`
- Filled during initialize handshake.
- Used for callback dispatch when CLI issues `hook_callback` requests.

### 9.4 Stream coordination memory
- `_first_result_event` used by `stream_input(...)` to delay stdin close when hooks or SDK MCP servers require continued bidirectional communication.

## 10. Parser Responsibilities for Memory Fields
In `src/claude_agent_sdk/_internal/message_parser.py`:
- extracts `uuid` and `tool_use_result` on `user` messages
- extracts `session_id` on `result` and `stream_event`
- preserves `parent_tool_use_id` associations

This parser is the boundary that transforms backend memory artifacts into typed SDK objects for app-level use.

## 11. Tests That Validate Memory Behavior

### 11.1 Unit/mocked tests
- Session option propagation (`continue_conversation`, `resume`) validated in `tests/test_transport.py` and `tests/test_integration.py`.
- `session_id` insertion behavior validated in `tests/test_streaming_client.py`.
- `uuid` and `tool_use_result` parsing validated in `tests/test_message_parser.py`.

### 11.2 E2E tests
- Partial message stream memory behavior (`StreamEvent`) in `e2e-tests/test_include_partial_messages.py`.
- Session dynamics (`set_model`, `set_permission_mode`, interrupt behavior) in `e2e-tests/test_dynamic_control.py`.
- Agent/settings context loading and large agent initialize payloads (relevant to context memory) in `e2e-tests/test_agents_and_settings.py`.

### 11.3 Changelog traceability
Memory-related additions explicitly documented:
- file checkpointing + rewind (0.1.15)
- `UserMessage.uuid` for checkpoint navigation (0.1.17)
- session forking (0.1.0)

## 12. Boundaries and Non-Goals
This SDK memory system intentionally does not provide:
- built-in vector database memory
- semantic retrieval/memory ranking layer
- autonomous long-term memory persistence independent of Claude Code sessions
- local transcript store management in Python package

Instead, it provides a typed and protocol-safe adapter over Claude Code’s session/memory mechanisms.

## 13. End-to-End Memory Flow Example
1. Configure options:
- `continue_conversation=True`, `resume=<old_session_id>`, `fork_session=True` (optional)
- `enable_file_checkpointing=True`
- `include_partial_messages=True`

2. Connect and send query with `ClaudeSDKClient`.

3. Consume stream:
- `SystemMessage(init)` establishes run context
- `StreamEvent` messages provide incremental generation state
- `AssistantMessage`/`ResultMessage` provide canonical outputs and `session_id`
- `UserMessage.uuid` values can be captured as rewind anchors

4. If needed, invoke:
- `rewind_files(<captured_uuid>)` to restore files to checkpoint.

5. Continue in same or forked session path depending on flags/options.

## 14. Practical Guidance for Implementers
If you are building on this SDK and need “memory features,” treat them as follows:

- Conversation memory: use session controls (`resume`, `continue_conversation`, `fork_session`) and explicitly manage session IDs in your app.
- Reversible file workflows: enable file checkpointing and persist `UserMessage.uuid` externally in your app state.
- Real-time UI memory: turn on partial messages and merge `StreamEvent` deltas into your client-side state model.
- Governance memory: implement hooks and permission callbacks to add deterministic context and policy decisions during execution.

## 15. Source File Map
- `src/claude_agent_sdk/types.py`
- `src/claude_agent_sdk/client.py`
- `src/claude_agent_sdk/query.py`
- `src/claude_agent_sdk/_internal/client.py`
- `src/claude_agent_sdk/_internal/query.py`
- `src/claude_agent_sdk/_internal/message_parser.py`
- `src/claude_agent_sdk/_internal/transport/subprocess_cli.py`
- `tests/test_message_parser.py`
- `tests/test_streaming_client.py`
- `tests/test_transport.py`
- `e2e-tests/test_include_partial_messages.py`
- `e2e-tests/test_dynamic_control.py`
- `e2e-tests/test_agents_and_settings.py`
- `CHANGELOG.md`

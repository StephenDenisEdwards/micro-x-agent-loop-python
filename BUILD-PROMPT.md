# Build Prompt: micro-x-agent-loop-python

You are building a **general-purpose, cost-aware AI agent loop** in Python 3.11+ with multi-provider LLM support, MCP tool orchestration, session persistence, a trigger broker for scheduled/webhook-driven runs, and an API server for programmatic access.

## Project Structure

```
micro-x-agent-loop-python/
├── pyproject.toml                          # Package metadata, dependencies, tool config
├── config.json                             # Config pointer (ConfigFile indirection)
├── config-base.json                        # Master config with all settings
├── run.sh / run.bat                        # Platform launchers
├── src/micro_x_agent_loop/
│   ├── __init__.py
│   ├── __main__.py                         # Entry point, CLI, REPL loop
│   ├── agent.py                            # Main orchestrator
│   ├── agent_channel.py                    # Bidirectional communication protocol + implementations
│   ├── agent_config.py                     # Runtime config dataclass
│   ├── analyze_costs.py                    # CLI cost analysis tool
│   ├── api_payload_store.py                # Ring buffer for API payload debugging
│   ├── app_config.py                       # Config loading, parsing, env expansion
│   ├── bootstrap.py                        # Runtime initialization wiring
│   ├── compaction.py                       # Conversation compaction strategies
│   ├── constants.py                        # Centralized magic numbers
│   ├── llm_client.py                       # Terminal spinner & retry utilities
│   ├── logging_config.py                   # Logging sink configuration
│   ├── metrics.py                          # Usage tracking, cost estimation, session accumulator
│   ├── mode_selector.py                    # Prompt mode analysis (Stage 1 pattern + Stage 2 LLM)
│   ├── provider.py                         # LLM provider protocol & factory
│   ├── system_prompt.py                    # System prompt construction with directives
│   ├── tool.py                             # Tool protocol & ToolResult dataclass
│   ├── tool_result_formatter.py            # Format structured tool results for LLM
│   ├── tool_search.py                      # On-demand tool discovery for large tool sets
│   ├── turn_engine.py                      # Single turn execution loop
│   ├── turn_events.py                      # TurnEngine callback protocol
│   ├── usage.py                            # UsageResult dataclass & cost estimation
│   ├── voice_ingress.py                    # Voice STT polling protocol
│   ├── voice_runtime.py                    # Voice session orchestration
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── common.py                       # Shared retry config (tenacity)
│   │   ├── anthropic_provider.py           # Anthropic streaming + prompt caching
│   │   └── openai_provider.py              # OpenAI streaming with format conversion
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── mcp_manager.py                  # MCP server lifecycle management
│   │   └── mcp_tool_proxy.py               # Wraps MCP tools as Tool protocol
│   ├── memory/
│   │   ├── __init__.py                     # Re-exports: MemoryStore, SessionManager, CheckpointManager, EventEmitter, prune_memory
│   │   ├── models.py                       # SessionRecord, MessageRecord dataclasses
│   │   ├── store.py                        # SQLite MemoryStore with schema init
│   │   ├── session_manager.py              # Session CRUD, message persistence, forking
│   │   ├── checkpoints.py                  # File checkpoint/snapshot/rewind
│   │   ├── events.py                       # EventEmitter with subscriber callbacks
│   │   ├── event_sink.py                   # AsyncEventSink for batched DB writes
│   │   ├── facade.py                       # MemoryFacade protocol + Null/Active implementations
│   │   └── pruning.py                      # Time-based session/message pruning
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── router.py                       # Slash command routing
│   │   ├── command_handler.py              # All slash command implementations
│   │   ├── prompt_commands.py              # Load /command prompts from .md files
│   │   └── voice_command.py                # Voice command argument parsing
│   ├── services/
│   │   ├── __init__.py
│   │   ├── session_controller.py           # Session display formatting
│   │   └── checkpoint_service.py           # Checkpoint display formatting
│   ├── broker/
│   │   ├── __init__.py
│   │   ├── service.py                      # BrokerService lifecycle (PID, signals, startup)
│   │   ├── scheduler.py                    # Cron scheduler with croniter
│   │   ├── dispatcher.py                   # RunDispatcher — spawns agent subprocesses
│   │   ├── runner.py                       # Subprocess runner for --run mode
│   │   ├── store.py                        # BrokerStore SQLite (jobs, runs, questions)
│   │   ├── response_router.py              # Routes results to channel adapters
│   │   ├── channels.py                     # ChannelAdapter protocol + HTTP/Log/Telegram/WhatsApp
│   │   ├── webhook_server.py               # FastAPI webhook + HITL API
│   │   ├── polling.py                      # PollingIngress for polling-mode channels
│   │   └── cli.py                          # CLI handlers for --broker/--job commands
│   └── server/
│       ├── __init__.py
│       ├── app.py                          # FastAPI app factory with lifespan, REST + WebSocket
│       ├── agent_manager.py                # Agent session cache with LRU eviction
│       └── ws_channel.py                   # WebSocketChannel (AgentChannel over WS)
└── tests/
    ├── __init__.py
    ├── fakes.py                            # FakeStreamProvider, FakeTool, fake managers
    ├── test_turn_engine.py
    ├── test_compaction_strategy.py
    ├── test_compaction_and_llm_utils.py
    ├── test_mode_selector.py
    ├── test_tool_search.py
    ├── test_metrics.py
    ├── test_usage.py
    ├── test_app_config.py
    ├── test_api_payload_store.py
    ├── test_ask_user.py
    ├── test_cost_reduction.py
    ├── test_llm_client_stream.py
    ├── agent/
    │   ├── test_agent_commands.py
    │   ├── test_voice_commands.py
    │   └── test_checkpoint_tracking_non_blocking.py
    ├── memory/
    │   ├── base.py                         # Shared test base with temp DB setup
    │   ├── test_session_manager.py
    │   ├── test_checkpoint_manager.py
    │   ├── test_checkpoint_track_paths.py
    │   ├── test_event_sink.py
    │   ├── test_event_callbacks.py
    │   ├── test_facade.py
    │   ├── test_pruning.py
    │   └── test_stress_and_retention.py
    ├── providers/
    │   ├── test_anthropic_provider.py
    │   └── test_openai_provider.py
    ├── broker/
    │   ├── test_store.py
    │   ├── test_scheduler.py
    │   └── test_autonomous.py
    ├── server/
    │   ├── config-test.json
    │   ├── test_app.py
    │   ├── test_agent_manager.py
    │   └── test_ws_channel.py
    └── integration/
        ├── conftest.py
        └── test_github_wrappers.py
```

## Dependencies (pyproject.toml)

```toml
[project]
name = "micro-x-agent-loop"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.42.0",
    "python-dotenv>=1.0.0",
    "tenacity>=9.0.0",
    "python-docx>=1.1.0",
    "beautifulsoup4>=4.12.0",
    "lxml>=5.0.0",
    "openai>=1.0.0",
    "httpx>=0.27.0",
    "google-api-python-client>=2.150.0",
    "google-auth-oauthlib>=1.2.0",
    "loguru>=0.7.0",
    "mcp>=1.0.0",
    "tiktoken>=0.7.0",
    "questionary>=2.0.0",
    "croniter>=1.3.0",
    "fastapi>=0.115.0",
    "uvicorn>=0.34.0",
    "tzdata>=2024.1; sys_platform == 'win32'",
]
[dependency-groups]
dev = ["ruff>=0.8.4", "mypy>=1.14.1", "pre-commit>=4.0.1", "pytest>=8.3.4", "pytest-asyncio>=0.25.0"]

[tool.ruff]
target-version = "py311"
line-length = 120
[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Every module uses `from __future__ import annotations`. Type hints on all public functions. Ruff-clean, 120-char lines.

---

## Core Protocols

### Tool Protocol (`tool.py`)

```python
@dataclass
class ToolResult:
    text: str
    structured: dict[str, Any] | None = None
    is_error: bool = False

@runtime_checkable
class Tool(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def input_schema(self) -> dict[str, Any]: ...
    @property
    def is_mutating(self) -> bool: ...
    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]: ...
    async def execute(self, tool_input: dict[str, Any]) -> ToolResult: ...
```

### LLMProvider Protocol (`provider.py`)

```python
@runtime_checkable
class LLMProvider(Protocol):
    async def stream_chat(self, model, max_tokens, temperature, system_prompt, messages, tools, *, channel=None) -> tuple[dict, list[dict], str, UsageResult]: ...
    async def create_message(self, model, max_tokens, temperature, messages) -> tuple[str, UsageResult]: ...
    def convert_tools(self, tools: list[Tool]) -> list[dict]: ...
```

Factory: `create_provider(provider_name, api_key, *, prompt_caching_enabled=False) -> LLMProvider` routes "anthropic" or "openai".

### AgentChannel Protocol (`agent_channel.py`)

```python
@runtime_checkable
class AgentChannel(Protocol):
    def emit_text_delta(self, text: str) -> None: ...
    def emit_tool_started(self, tool_use_id: str, tool_name: str) -> None: ...
    def emit_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None: ...
    def emit_turn_complete(self, usage: dict[str, Any]) -> None: ...
    def emit_error(self, message: str) -> None: ...
    async def ask_user(self, question: str, options: list[dict[str, str]] | None = None) -> str: ...
```

Four implementations:
1. **TerminalChannel** — interactive CLI with thread-based spinner (`_Spinner`) and questionary prompts. Spinner uses `_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"` with 0.08s frame rate. Has `begin_streaming()`, `end_streaming()`, `print_line()` helpers.
2. **BufferedChannel** — for `--run` autonomous mode; accumulates text/tool_events/errors/turn_usages in lists; `ask_user()` returns timeout message.
3. **BrokerChannel** — for broker subprocess HITL; posts questions to broker HTTP API, polls for answers with configurable timeout/interval.
4. **WebSocketChannel** (in `server/ws_channel.py`) — sends JSON frames over WebSocket; uses `asyncio.Future` + counter for ask_user flow; `receive_answer(question_id, answer)` resolves futures.

Also defines `ASK_USER_SCHEMA` — the JSON schema for the ask_user pseudo-tool injected into LLM tool lists when a channel is present.

### TurnEvents Protocol (`turn_events.py`)

```python
@runtime_checkable
class TurnEvents(Protocol):
    def on_append_message(self, role: str, content: str | list[dict]) -> str | None: ...
    def on_user_message_appended(self, message_id: str | None) -> None: ...
    async def on_maybe_compact(self) -> None: ...
    def on_ensure_checkpoint_for_turn(self, tool_use_blocks: list[dict]) -> None: ...
    def on_maybe_track_mutation(self, tool_name: str, tool: Tool, tool_input: dict) -> None: ...
    def on_record_tool_call(self, tool_call_id, tool_name, tool_input, result_text, is_error, message_id) -> None: ...
    def on_tool_started(self, tool_use_id: str, tool_name: str) -> None: ...
    def on_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None: ...
    def on_api_call_completed(self, usage: UsageResult, call_type: str) -> None: ...
    def on_tool_executed(self, tool_name, result_chars, duration_ms, is_error, was_summarized) -> None: ...
```

`BaseTurnEvents` provides no-op defaults.

### CompactionStrategy Protocol (`compaction.py`)

```python
class CompactionStrategy(Protocol):
    async def maybe_compact(self, messages: list[dict]) -> list[dict]: ...
```

### MemoryFacade Protocol (`memory/facade.py`)

```python
@runtime_checkable
class MemoryFacade(Protocol):
    @property
    def session_manager(self) -> Any: ...
    @property
    def checkpoint_manager(self) -> Any: ...
    @property
    def active_session_id(self) -> str | None: ...
    @active_session_id.setter
    def active_session_id(self, value: str | None) -> None: ...
    def append_message(self, role, content) -> str | None: ...
    def ensure_checkpoint_for_turn(self, tool_use_blocks, *, user_message_id, user_message_text, current_checkpoint_id) -> str | None: ...
    def maybe_track_mutation(self, tool_name, tool, tool_input, checkpoint_id) -> None: ...
    def record_tool_call(self, *, tool_call_id, tool_name, tool_input, result_text, is_error, message_id) -> None: ...
    def emit_tool_started(self, tool_use_id, tool_name) -> None: ...
    def emit_tool_completed(self, tool_use_id, tool_name, is_error) -> None: ...
    def load_messages(self, session_id) -> list[dict]: ...
```

Two implementations: `NullMemoryFacade` (no-op) and `ActiveMemoryFacade` (delegates to real managers).

---

## Architecture Flow

```
__main__.py
  → _parse_cli_args()  # --config, --run, --session, --broker, --job, --server
  → load_json_config() → parse_app_config() → resolve_runtime_env()
  → Route: broker commands → broker/cli.py
  → Route: server commands → server/app.py (run_server)
  → Route: agent → bootstrap_runtime() → REPL loop or one-shot

bootstrap_runtime(app, env, *, autonomous)
  → setup_logging()
  → McpManager(server_configs).connect_all() → list[Tool]
  → Create compaction strategy (SummarizeCompactionStrategy or NoneCompactionStrategy)
  → If memory_enabled: MemoryStore → AsyncEventSink → SessionManager → CheckpointManager → EventEmitter
  → Resolve session (resume/continue/new)
  → Prune old memory
  → Load user memory (MEMORY.md, max N lines)
  → Create AgentChannel (BrokerChannel if HITL env, BufferedChannel if autonomous, TerminalChannel otherwise)
  → get_system_prompt(user_memory, directives...)
  → Agent(AgentConfig(...))
  → Return AppRuntime(agent, mcp_manager, memory_store, event_sink, mcp_tools, log_descriptions)

Agent.__init__(config)
  → create_provider() → LLMProvider
  → provider.convert_tools(tools) → converted_tools
  → Build tool_map: {tool.name: tool}
  → ToolSearchManager if tool_search active
  → TurnEngine(provider, model, tools, events=self, channel, ...)
  → CommandRouter with handlers
  → SessionAccumulator for metrics
  → MemoryFacade (Active or Null)
  → SessionController, CheckpointService
  → CommandHandler
  → initialize_session() loads persisted messages

Agent.run(user_message)
  → Check for /commands → CommandRouter.try_handle()
  → If mode_analysis_enabled: analyze_prompt() → Stage 1 signals
  → If ambiguous + stage2 enabled: _classify_ambiguous() → Stage 2 LLM classification
  → Increment turn_number
  → TurnEngine.run(messages, user_message)

TurnEngine.run(messages, user_message)
  → Append user message via events.on_append_message()
  → events.on_maybe_compact()
  → resolve_system_prompt(template) — replaces {current_date}
  → Get tools (tool_search filtered or all)
  → Loop:
    → provider.stream_chat(model, max_tokens, temp, system_prompt, messages, tools, channel=channel)
      → If channel present: inject ASK_USER_SCHEMA into tools
      → Provider streams tokens, calls channel.emit_text_delta() for each delta
    → Record API call metrics
    → Append assistant message
    → If stop_reason == "max_tokens" and no tool_use: retry with continuation (up to MAX_TOKENS_RETRIES)
    → If tool_use blocks present:
      → Classify into: search blocks, ask_user blocks, regular blocks
      → Handle search blocks inline (ToolSearchManager.handle_tool_search)
      → Handle ask_user blocks inline (channel.ask_user)
      → For regular blocks:
        → events.on_ensure_checkpoint_for_turn() — snapshot files before mutation
        → execute_tools(blocks) — parallel async execution:
          → For each block: tool.execute(input) → ToolResult
          → Truncate result if > max_tool_result_chars
          → Optionally summarize via summarization_provider if > threshold
          → events.on_maybe_track_mutation(), on_record_tool_call(), on_tool_executed()
      → Merge all results in original order
      → Append tool_result message
      → events.on_maybe_compact()
      → Continue loop
    → If no tool_use: return (user_message_id, assistant_message_id)
```

---

## Module Details

### UsageResult (`usage.py`)

```python
@dataclass(frozen=True)
class UsageResult:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    duration_ms: float
    time_to_first_token_ms: float
    provider: str
    model: str
    message_count: int
    tool_schema_count: int
    stop_reason: str
```

`PRICING` dict maps model names to `(input, output, cache_read, cache_write)` $/MTok tuples. `estimate_cost(usage)` calculates USD. Uses prefix matching for model lookup.

### Constants (`constants.py`)

Key values: `DEFAULT_MAX_TOKENS=8192`, `DEFAULT_MAX_TOOL_RESULT_CHARS=40000`, `DEFAULT_MAX_CONVERSATION_MESSAGES=50`, `DEFAULT_TOOL_RESULT_SUMMARIZATION_THRESHOLD=4000`, `MAX_TOKENS_RETRIES=3`, `DEFAULT_COMPACTION_THRESHOLD_TOKENS=80000`, `DEFAULT_PROTECTED_TAIL_MESSAGES=6`, `COMPACTION_PREVIEW_TOTAL=700`, `COMPACTION_PREVIEW_HEAD=500`, `COMPACTION_PREVIEW_TAIL=200`, `COMPACTION_SUMMARIZE_INPUT_CAP=100000`, `TOOL_SEARCH_MAX_LOAD=20`, `TOOL_SEARCH_DEFAULT_THRESHOLD_PERCENT=40`, `CHARS_TO_TOKENS_DIVISOR=4`, plus memory defaults and context window lookup dict.

### Config System (`app_config.py`)

`AppConfig` dataclass with ~75 fields covering model, tools, compaction, memory, cost reduction, mode analysis, logging, broker, working directory, etc.

`load_json_config(config_path=None) -> tuple[dict, str]`:
- Resolution: CLI arg → look for `ConfigFile` key (pointer to actual file) → `config.json` default
- Process `Base` key: load base file, deep-merge overlay on top (recursive)
- `_expand_env_vars()`: replaces `${ENV_VAR}` in all string values recursively
- Returns (config_dict, source_path)

`parse_app_config(config) -> AppConfig`: maps dict keys to dataclass fields with defaults.
`resolve_runtime_env(provider_name) -> RuntimeEnv`: reads `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` from environment.

### Providers

**AnthropicProvider** (`providers/anthropic_provider.py`):
- Uses `anthropic.AsyncAnthropic`
- `stream_chat()`: streaming with prompt caching support (wraps system prompt and last tool with `cache_control: {"type": "ephemeral"}`)
- Processes `content_block_delta` events, extracts `text_delta`, calls `channel.emit_text_delta()`
- Tracks `time_to_first_token_ms`
- Retry with tenacity: `RateLimitError`, `APIConnectionError`, `APITimeoutError` — exponential backoff 10-320ms, 5 attempts
- `create_message()`: non-streaming for compaction/summarization

**OpenAIProvider** (`providers/openai_provider.py`):
- Uses `openai.AsyncOpenAI`
- `_to_openai_messages()`: converts internal Anthropic-style messages to OpenAI format (handles tool_use→tool_calls, tool_result→tool role)
- `_to_openai_tools()`: wraps tools in `{"type": "function", "function": {...}}`
- `_STOP_REASON_MAP`: maps OpenAI finish reasons to internal format (`"stop"→"end_turn"`, `"tool_calls"→"tool_use"`, `"length"→"max_tokens"`)
- Accumulates tool_calls incrementally by index from stream chunks
- Reconstructs output in Anthropic-style format for unified downstream handling

**common.py**: `default_retry_kwargs(exception_types)` returns tenacity config dict with exponential backoff (10-320ms, 5 attempts).

### MCP System

**McpManager** (`mcp/mcp_manager.py`):
- `__init__(server_configs: dict[str, dict])` — configs keyed by server name
- `connect_all() -> list[Tool]`: starts all servers in parallel using `_ServerConnection` per server
- `_ServerConnection`: manages one server's lifecycle via asyncio.Task + Event pattern (NOT AsyncExitStack)
  - `_run_stdio()`: uses `mcp.stdio_client` with merged env vars
  - `_run_http()`: uses `mcp.client.streamable_http.streamable_http_client`
  - Creates `ClientSession` with logging callback → `session.initialize()` → `session.list_tools()` → builds proxies
  - Waits on `_shutdown` Event to keep alive
- `_mcp_logging_callback()`: forwards MCP server notifications to terminal via `print_through_spinner()` and to loguru
- `_build_proxies()`: extracts `destructiveHint` annotation for `is_mutating`, `outputSchema` if present
- `close()`: stops all connections (cancel tasks, 5s timeout)

**McpToolProxy** (`mcp/mcp_tool_proxy.py`):
- Implements Tool protocol wrapping MCP tool definition + ClientSession
- `name` returns `f"{server_name}__{tool_name}"` (namespaced)
- `execute()`: calls `session.call_tool(tool_name, arguments=tool_input)`, extracts TextContent blocks, checks `result.isError`, extracts `structuredContent` if present
- `predict_touched_paths()`: returns empty list

### Compaction (`compaction.py`)

**NoneCompactionStrategy**: returns messages unchanged.

**SummarizeCompactionStrategy**:
- `__init__(provider, model, threshold_tokens, protected_tail_messages, on_compaction_completed, smart_trigger_enabled)`
- `update_actual_tokens(input_tokens)`: receives actual API token count for smart triggering
- `maybe_compact(messages)`:
  1. Estimate tokens (smart trigger uses actual API tokens; fallback uses tiktoken `cl100k_base`)
  2. If below threshold → return unchanged
  3. Protect last N messages (`protected_tail_messages`)
  4. `_adjust_boundary()`: pull boundary back if it would split tool_use/tool_result pairs
  5. `_summarize()`: call LLM to summarize compactable portion (caps input at `COMPACTION_SUMMARIZE_INPUT_CAP`)
  6. `_rebuild_messages()`: merge summary into first message, append protected tail
  7. Fire `on_compaction_completed` callback

Token estimation: `estimate_tokens(messages)` uses tiktoken on JSON-serialized content.

### System Prompt (`system_prompt.py`)

`get_system_prompt(user_memory, user_memory_enabled, concise_output_enabled, tool_search_active, working_directory, autonomous, hitl_enabled) -> str`:
- Base prompt: capabilities, tool access, conciseness, file handling, error recovery
- Platform detection (Windows vs Unix)
- Conditional directives: `_TOOL_SEARCH_DIRECTIVE`, `_ASK_USER_DIRECTIVE` or `_AUTONOMOUS_DIRECTIVE`, `_HITL_DIRECTIVE`, `_CONCISE_OUTPUT_DIRECTIVE`, `_USER_MEMORY_GUIDANCE`
- Contains `{current_date}` placeholder

`resolve_system_prompt(template) -> str`: replaces `{current_date}` with formatted today's date.

### Mode Analysis (`mode_selector.py`)

Stage 1 pattern matching with signal detectors:
- `_detect_batch()`, `_detect_scoring()`, `_detect_stats()`, `_detect_mandatory_fields()`, `_detect_structured_output()`, `_detect_multiple_sources()`, `_detect_reproducibility()`
- Each returns `DetectedSignal(name, strength, matched_text)` or None
- Signal strengths: STRONG, MODERATE, SUPPORTIVE

`analyze_prompt(text) -> ModeAnalysis`: runs all detectors, recommends COMPILED (2+ strong), PROMPT (no signals), or AMBIGUOUS.

Stage 2: `build_stage2_prompt()` creates classification prompt for LLM; `parse_stage2_response()` extracts decision.

### Metrics (`metrics.py`)

Metric builders: `build_api_call_metric()`, `build_tool_execution_metric()`, `build_compaction_metric()`, `build_session_summary_metric()`. All return dicts logged via `emit_metric()` (loguru with `metrics=True` extra).

`SessionAccumulator`: accumulates per-session totals (tokens, cost, tool calls, errors, compaction events). Tracks `model_subtotals` dict and `api_call_log` list. `format_summary()` returns human-readable multi-line text.

### Tool Search (`tool_search.py`)

`TOOL_SEARCH_SCHEMA`: pseudo-tool definition injected when tool_search is active.

`should_activate_tool_search(setting, converted_tools, model, threshold_percent) -> bool`: checks if tool schemas exceed N% of context window.

`ToolSearchManager`:
- `__init__(all_tools, converted_tools)`: builds `tool_index = {name: (Tool, converted_dict)}`
- `begin_turn()`: clears loaded tools for new turn
- `get_tools_for_api_call()`: returns `[tool_search_schema] + loaded_tools`
- `handle_tool_search(query)`: term-matches tool names/descriptions, loads top matches (up to `TOOL_SEARCH_MAX_LOAD`), returns formatted results

### Tool Result Formatter (`tool_result_formatter.py`)

`ToolResultFormatter`: formats `ToolResult.structured` into text using per-tool config from `ToolFormatting` settings.
- Supports formats: json, text, table, key_value
- Per-tool config can specify `max_rows`, `fields`, format type
- Falls back to `default_format`

### API Payload Store (`api_payload_store.py`)

`ApiPayload` dataclass: timestamp, model, system_prompt, messages, tools_count, response_message, stop_reason, usage.
`ApiPayloadStore`: fixed-size `collections.deque` ring buffer. `record()` appends, `get(index)` retrieves by reverse index.

### Logging (`logging_config.py`)

`LogConsumer` protocol with `register(level)` and `describe(level)` methods.

Implementations:
- `ConsoleLogConsumer`: stderr, singleton, adjustable level
- `FileLogConsumer`: file with rotation/retention
- `MetricsLogConsumer`: metrics.jsonl (filters `record["extra"].get("metrics")`)
- `ApiPayloadLogConsumer`: api_payloads.jsonl (filters `record["extra"].get("api_payload")`)

`setup_logging(level, consumers)` configures loguru sinks, returns descriptions.

### LLM Client (`llm_client.py`)

`Spinner`: thread-based terminal spinner using `\r` overwrite. `_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"`. Global `_active_spinner` reference.
`print_through_spinner(text)`: clears spinner, prints, restarts.
`_on_retry(retry_state)`: tenacity callback logging retry attempts.

### Voice System

**VoiceIngress** protocol (`voice_ingress.py`): `async stream_events(*, session_id, since_seq) -> AsyncIterator[dict]`

**PollingVoiceIngress**: polls `stt_get_updates` MCP tool, yields events. `_parse_json_object()` handles markdown-wrapped JSON.

**VoiceRuntime** (`voice_runtime.py`): orchestrates STT sessions. `start()`, `stop()`, `status()`, `events()`, `devices()`. Uses `_poll_loop()` and `_consumer_loop()` asyncio tasks with internal queue.

---

## Memory System

### SQLite Schema (7 tables in memory.db)

```sql
sessions(id PK, parent_session_id, created_at, updated_at, status, model, metadata_json)
messages(id PK, session_id FK, seq, role, content_json, created_at, token_estimate)
tool_calls(id PK, session_id FK, message_id, tool_name, input_json, result_text, is_error, created_at)
checkpoints(id PK, session_id FK, user_message_id, created_at, scope_json)
checkpoint_files(checkpoint_id FK, path, existed_before, backup_blob, backup_path)
events(id PK, session_id FK, type, payload_json, created_at)
-- Plus multiple indexes on session_id, message_id, etc.
```

**MemoryStore**: thin SQLite wrapper with `execute()`, `executemany()`, `commit()`, `rollback()`, `@contextmanager transaction()`.

**SessionManager**: session CRUD, message append/load, tool call recording, session forking, title management, summary building. Token estimation via `estimate_tokens()` from compaction module.

**CheckpointManager**: `create_checkpoint()` → `track_paths()` (binary file backup) → `rewind_files()` (restore from backup). Respects `working_directory` boundaries. `write_tools_only` mode.

**EventEmitter**: pub/sub with `on(event_type, callback)`, `on_all(callback)`, `off()`, `emit()`. Persists via AsyncEventSink or direct DB insert.

**AsyncEventSink**: batched async DB writes with configurable `batch_size` and `flush_interval_seconds`. Queue-based with background task.

**ActiveMemoryFacade**: bridges Agent to memory subsystem. `_MUTATING_TOOL_NAMES` set for non-MCP mutation detection. Delegates to SessionManager, CheckpointManager, EventEmitter.

**Pruning**: `prune_memory(store, *, max_sessions, max_messages_per_session, retention_days)` — time-based cleanup.

---

## Broker System

### SQLite Schema (4 tables in broker.db)

```sql
broker_jobs(id PK, name, trigger_type, cron_expr, timezone, enabled, prompt_template, session_id, config_profile, response_channel, response_target, overlap_policy, timeout_seconds, hitl_enabled, hitl_timeout_seconds, max_retries, retry_delay_seconds, created_at, updated_at, last_run_at, next_run_at)
broker_runs(id PK, job_id FK, trigger_source, prompt, session_id, status, started_at, completed_at, result_summary, error_text, response_channel, response_target, response_sent, response_error, attempt_number, scheduled_at)
broker_questions(id PK, run_id FK, question_text, options, answer, status, asked_at, answered_at, timeout_at)
```

### Broker Architecture

```
BrokerService.start()
  → Acquire PID file (atomic)
  → BrokerStore(db_path)
  → ResponseRouter(adapters)
  → RunDispatcher(store, response_router, max_concurrent_runs, broker_url)
  → Scheduler(store, dispatcher, poll_interval, recovery_policy)
  → WebhookServer(store, dispatcher, adapters, host, port, api_secret)
  → PollingIngress per polling-capable adapter
  → Register SIGTERM/SIGINT handlers
  → Run until shutdown
```

**Scheduler**: polls for due jobs via cron expressions (croniter). Recovery policies: "skip" or "run_once" for missed runs. `overlap_policy: "skip_if_running"`.

**RunDispatcher**: spawns agent as subprocess (`python -m micro_x_agent_loop --run "prompt"`). Sets HITL env vars if enabled (`BROKER_URL`, `BROKER_RUN_ID`, `BROKER_HITL_TIMEOUT`). Updates run status, routes response, schedules retries on failure.

**Runner**: `run_agent()` async function — subprocess with timeout, output truncation (10MB cap), returns `RunResult(exit_code, stdout, stderr)`.

**Channel Adapters**: `ChannelAdapter` protocol with `verify_request`, `parse_webhook`, `poll_messages`, `send_response`, `send_question`. Built-in: `HttpAdapter`, `LogAdapter`, `TelegramAdapter`, `WhatsAppAdapter`. Factory: `build_adapters(channels_config)`.

**WebhookServer**: FastAPI app with routes for health, jobs, runs, HITL questions, and webhook triggers. Bearer token auth middleware (skips /api/health).

**PollingIngress**: async loop calling `adapter.poll_messages()` with exponential backoff on errors.

**CLI** (`broker/cli.py`): `handle_broker_command()` for start/stop/status, `handle_job_command()` for add/list/remove/enable/disable/run-now/runs.

---

## API Server (`server/`)

### Architecture

```
create_app(config_path, api_secret, cors_origins, max_sessions, session_timeout_minutes) -> FastAPI
  Lifespan:
    Startup: load config → McpManager.connect_all() → MemoryStore → AsyncEventSink → AgentManager
    Shutdown: AgentManager.shutdown_all() → close MCP/event_sink

AgentManager:
  - LRU cache of Agent instances keyed by session_id
  - _AgentSlot(agent, session_id, last_access) with touch()
  - get_or_create(session_id, channel) → evicts expired + oldest if over capacity
  - _create_agent() builds Agent with full config (compaction, memory, provider, system prompt)
  - destroy(session_id), list_sessions(), shutdown_all()
```

### Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | /api/health | Status, active sessions, tool count, memory flag |
| POST | /api/sessions | Create new session (requires memory) |
| GET | /api/sessions | List active sessions |
| GET | /api/sessions/{id} | Get session details |
| DELETE | /api/sessions/{id} | Delete session + shutdown agent |
| GET | /api/sessions/{id}/messages | Get session messages |
| POST | /api/chat | Synchronous chat (BufferedChannel) |
| WS | /api/ws/{session_id} | Streaming WebSocket chat |

**POST /api/chat**: accepts `{message, session_id?}`, creates BufferedChannel, runs `agent.run(message)`, returns `{session_id, response, errors}`.

**WS /api/ws/{session_id}**: accepts connection, creates WebSocketChannel, receives JSON frames:
- `{type: "message", text}` → calls `agent.run(text)`
- `{type: "answer", question_id, text}` → calls `channel.receive_answer()`
- `{type: "ping"}` → responds `{type: "pong"}`

WebSocket emits: `text_delta`, `tool_started`, `tool_completed`, `turn_complete`, `error`, `question`.

**Auth**: optional Bearer token via `SERVER_API_SECRET` env var. Health endpoint skips auth.

### `run_server()` function

Called from `__main__.py` when `--server start` is passed. Creates app, runs uvicorn (default host=127.0.0.1, port=8321).

---

## Command System

### Router (`commands/router.py`)

`CommandRouter.__init__()` takes named handler callbacks. `try_handle(user_message) -> bool | str` routes by prefix:
- `/help`, `/command`, `/cost`, `/rewind`, `/checkpoint`, `/session`, `/voice`, `/memory`, `/tools`, `/tool`, `/console-log-level`, `/debug`

Returns False (not a command), True (handled), or str (prompt to execute for /command).

### Handler (`commands/command_handler.py`)

`CommandHandler` implements all slash commands:
- `/help` — prints available commands
- `/cost` — shows SessionAccumulator summary
- `/session [list|new|name|resume|fork]` — session management
- `/rewind <id>` — restore files from checkpoint
- `/checkpoint [list|rewind]` — checkpoint management
- `/memory [list|edit|reset]` — user memory management
- `/tools mcp` — list MCP server tools
- `/tool [name] [schema|config]` — tool inspection
- `/command <name>` — loads prompt from commands directory
- `/voice [start|stop|status|devices|events]` — voice control
- `/debug show-api-payload [N]` — API payload inspection
- `/console-log-level [level]` — adjust console logging

### Prompt Commands (`commands/prompt_commands.py`)

`PromptCommandStore(commands_dir)`: loads `.md` files from commands directory. `list_commands()` returns `(name, first_line_description)`. `load_command(name)` returns full text. Supports `$ARGUMENTS` placeholder replacement.

---

## Entry Point (`__main__.py`)

### CLI Arguments

`_parse_cli_args()` parses: `--config PATH`, `--run PROMPT`, `--session ID`, `--broker SUBCOMMAND`, `--job SUBCOMMAND ARGS`, `--server SUBCOMMAND`

### Main Flow

```python
async def main():
    install_transport_cleanup_hook()  # Windows asyncio warning suppression
    args = _parse_cli_args()
    app, source = load_json_config(args.get("config"))
    app = parse_app_config(app)

    if args.get("broker") or args.get("job"):
        handle_broker_command(args, app) / handle_job_command(args, app)
        return

    if args.get("server"):
        await run_server(config_path=args.get("config"), ...)
        return

    env = resolve_runtime_env(app.provider_name)
    runtime = await bootstrap_runtime(app, env, autonomous=bool(args.get("run")))

    if args.get("run"):
        await _run_oneshot(app, env, args["run"], args.get("session"))
    else:
        # REPL loop
        while True:
            user_input = input("user> ")
            if user_input in ("exit", "quit"): break
            task = asyncio.create_task(runtime.agent.run(user_input))
            esc_watcher.start(task, loop)  # Windows ESC cancellation
            await task
```

**_EscWatcher**: Windows-specific ESC key detector using ctypes `kernel32.ReadConsoleInputW`. Background thread polls console input for VK_ESCAPE (0x1B), cancels asyncio task.

**_McpNotificationFilter**: suppresses noisy MCP SDK validation warnings via `logging.Filter`.

---

## Testing Approach

### Test Fakes (`tests/fakes.py`)

**FakeStreamProvider**: queues responses via `queue(text, tool_use_blocks, stop_reason, usage)`. `stream_chat()` pops first queued response. `convert_tools()` returns simple dicts.

**FakeTool**: configurable name, description, schema, execute result/side_effect, is_mutating, touched_paths. Tracks `execute_calls` count.

**FakeProvider**: for compaction tests. Records `create_message` calls, returns configurable summary text.

**FakeEventEmitter**: records `emit()` calls as `(args, kwargs)` tuples.

**SessionManagerFake**: stub with `load_messages()`, `append_message()`, `record_tool_call()`, etc.

**CheckpointManagerFake**: tracks `created` and `rewinds` lists.

### Test Patterns

- Unit tests use `unittest.TestCase` (run via pytest)
- Async tests use `pytest-asyncio`
- Memory tests share `tests/memory/base.py` with temp SQLite DB setup
- Provider tests mock the underlying API clients
- Server tests use `fastapi.testclient.TestClient`
- Integration tests in `tests/integration/` test full stack against real APIs

---

## Configuration (`config-base.json`)

```json
{
    "Provider": "anthropic",
    "Model": "claude-sonnet-4-5-20250929",
    "MaxTokens": 32768,
    "Temperature": 0.7,
    "CompactionStrategy": "summarize",
    "CompactionModel": "claude-haiku-4-5-20251001",
    "CompactionThresholdTokens": 80000,
    "ProtectedTailMessages": 6,
    "PromptCachingEnabled": true,
    "ToolResultSummarizationEnabled": false,
    "SmartCompactionTriggerEnabled": true,
    "ConciseOutputEnabled": true,
    "ToolSearchEnabled": "auto:40",
    "MemoryEnabled": true,
    "MemoryDbPath": ".micro_x/memory.db",
    "EnableFileCheckpointing": true,
    "CheckpointWriteToolsOnly": true,
    "UserMemoryEnabled": true,
    "ModeAnalysisEnabled": true,
    "Stage2ClassificationEnabled": true,
    "Stage2Model": "claude-haiku-4-5-20251001",
    "MetricsEnabled": true,
    "McpServers": {
        "server-name": {
            "transport": "stdio",
            "command": "node",
            "args": ["path/to/server.js"],
            "env": {"KEY": "value"}
        }
    },
    "ToolFormatting": {
        "tool_name": {"format": "json", "max_rows": 20}
    },
    "LogLevel": "INFO",
    "LogConsumers": [
        {"type": "console"},
        {"type": "file", "path": "logs/agent.log", "rotation": "10 MB", "retention": "7 days"},
        {"type": "api_payload", "path": "logs/api_payloads.jsonl", "rotation": "50 MB", "retention": "3 days"}
    ]
}
```

Config supports `ConfigFile` indirection and `Base` inheritance for variants.

---

## Key Design Decisions

1. **Protocol-first architecture** — Tool, LLMProvider, AgentChannel, TurnEvents, CompactionStrategy, MemoryFacade, ChannelAdapter, VoiceIngress all use `@runtime_checkable Protocol`
2. **Internal message format is Anthropic-style** — OpenAI provider converts to/from OpenAI format at the boundary
3. **All tools are MCP servers** (TypeScript, external repos) — only pseudo-tools (ask_user, tool_search) are Python
4. **Callback pattern** — TurnEngine calls Agent (via TurnEvents) for lifecycle hooks, not the reverse
5. **Channel abstraction** — same agent code works for CLI, autonomous, broker HITL, and WebSocket
6. **Task-based MCP lifecycle** — asyncio.Task + Event, not AsyncExitStack
7. **Cost-aware by default** — prompt caching, smart compaction triggers, tool result summarization (optional), detailed metrics
8. **Checkpoint before mutation** — files are snapshot before any mutating tool executes, enabling rewind
9. **No Python tools** — tools are TypeScript MCP servers in separate repos
10. **structuredContent does NOT propagate** through Python MCP SDK — McpToolProxy extracts text as fallback

# Claude Agent SDK Architecture -- Deep Research

**Date:** 2026-02-24
**Status:** Complete
**Subject:** Anthropic Claude Agent SDK (Python + TypeScript) -- architecture, agent loop, tools, multi-agent, guardrails, MCP, context management

---

## 1. Overview

The **Claude Agent SDK** (formerly "Claude Code SDK") is Anthropic's official SDK for building autonomous AI agents powered by Claude. It exposes the same agent loop, tools, and context management that power **Claude Code** (Anthropic's CLI coding assistant) as a programmable library.

### Core Philosophy

The SDK's central premise is: **Claude executes tools directly instead of asking you to implement tool execution.** Unlike the low-level Anthropic Client SDK (where you write the `while stop_reason == "tool_use"` loop yourself), the Agent SDK handles the entire orchestration cycle -- tool dispatch, result collection, retries, context management -- so your code just consumes a stream of messages.

### Language & Tech Stack

| Dimension | Detail |
|-----------|--------|
| **Languages** | Python 3.10+, TypeScript (Node.js 18+) |
| **Python package** | `pip install claude-agent-sdk` |
| **TypeScript package** | `npm install @anthropic-ai/claude-agent-sdk` |
| **Python repo** | [github.com/anthropics/claude-agent-sdk-python](https://github.com/anthropics/claude-agent-sdk-python) |
| **TypeScript repo** | [github.com/anthropics/claude-agent-sdk-typescript](https://github.com/anthropics/claude-agent-sdk-typescript) |
| **Demos repo** | [github.com/anthropics/claude-agent-sdk-demos](https://github.com/anthropics/claude-agent-sdk-demos) |
| **License** | MIT license on the SDK code; usage governed by [Anthropic Commercial Terms of Service](https://www.anthropic.com/legal/commercial-terms) |
| **Auth** | `ANTHROPIC_API_KEY` env var; also supports Amazon Bedrock, Google Vertex AI, Microsoft Azure AI Foundry |

### Architecture Note -- CLI Bundling

A critical implementation detail: the Python SDK **bundles the Claude Code CLI** inside the package. The SDK communicates with Claude by spawning this CLI as a subprocess and exchanging JSON over stdin/stdout. The `ClaudeSDKClient` manages this subprocess lifecycle. You can override the CLI path via `ClaudeAgentOptions(cli_path="/path/to/claude")`.

---

## 2. Agent Loop Lifecycle

The core feedback loop is: **gather context -> take action -> verify work -> repeat**.

### Two Entry Points

The Python SDK provides two ways to drive the loop:

| Feature | `query()` | `ClaudeSDKClient` |
|---------|-----------|-------------------|
| **Session** | New session each call | Reuses same session |
| **Conversation** | Single exchange | Multi-exchange, maintains context |
| **Connection** | Managed automatically | Manual control via `connect()`/`disconnect()` |
| **Interrupts** | Not supported | Supported via `interrupt()` |
| **Hooks** | Not supported | Supported |
| **Custom Tools (MCP)** | Not supported | Supported |
| **Continue Chat** | New session each time | Maintains conversation |
| **Use Case** | One-off tasks, CI/CD | Interactive apps, multi-turn workflows |

**Note:** The table above reflects the current documented distinction. `query()` is simpler and creates a fresh session each time. `ClaudeSDKClient` provides full control.

### End-to-End Turn Flow

```
1. User calls query(prompt="...", options=...) or client.query(prompt)
2. SDK spawns (or reuses) the Claude Code CLI subprocess
3. SDK sends the prompt + config as JSON over stdin
4. CLI sends prompt to Claude API with system prompt + tool definitions
5. Claude responds with either:
   a. Text (reasoning) -> streamed as AssistantMessage
   b. Tool use request -> SDK executes tool automatically
   c. End turn signal -> streamed as ResultMessage
6. If tool use:
   a. SDK runs PreToolUse hooks (can block/modify/allow)
   b. SDK executes the tool (built-in or MCP)
   c. SDK runs PostToolUse hooks (can log/transform)
   d. Tool result sent back to Claude
   e. Go to step 5
7. Loop ends when Claude issues end_turn or max_turns reached
8. ResultMessage emitted with cost, duration, session_id
```

### Streaming

The `async for` loop yields messages as Claude works:

```python
async for message in query(prompt="Fix the bug in auth.py", options=options):
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if hasattr(block, "text"):
                print(block.text)        # Claude's reasoning
            elif hasattr(block, "name"):
                print(f"Tool: {block.name}")  # Tool being called
    elif isinstance(message, ResultMessage):
        print(f"Done: {message.subtype}")  # "success" or "error_during_execution"
```

For finer-grained streaming, set `include_partial_messages=True` in options to receive `StreamEvent` objects containing raw API stream events.

### Message Types

```python
# Union of all messages yielded by the agent loop
Message = UserMessage | AssistantMessage | SystemMessage | ResultMessage | StreamEvent

# Content blocks within AssistantMessage
ContentBlock = TextBlock | ThinkingBlock | ToolUseBlock | ToolResultBlock
```

Key message classes:

| Class | Key Fields | When Emitted |
|-------|-----------|--------------|
| `SystemMessage` | `subtype` ("init"), `data` (session_id, mcp_servers, tools) | Session start |
| `AssistantMessage` | `content: list[ContentBlock]`, `model: str` | Claude's reasoning and tool calls |
| `ResultMessage` | `subtype`, `duration_ms`, `duration_api_ms`, `is_error`, `num_turns`, `session_id`, `total_cost_usd`, `usage`, `result`, `structured_output` | End of turn |
| `StreamEvent` | `uuid`, `session_id`, `event` (raw API event), `parent_tool_use_id` | During streaming (if `include_partial_messages=True`) |

---

## 3. Agent Definition & Configuration

### `ClaudeAgentOptions` -- Full Configuration Surface

This is the central configuration dataclass. Every knob for agent behavior lives here:

```python
@dataclass
class ClaudeAgentOptions:
    # --- Tool access ---
    tools: list[str] | ToolsPreset | None = None
    allowed_tools: list[str] = []           # Whitelist of tool names
    disallowed_tools: list[str] = []        # Blacklist of tool names

    # --- Prompt ---
    system_prompt: str | SystemPromptPreset | None = None
    # Can be a raw string, or {"type": "preset", "preset": "claude_code", "append": "..."}

    # --- Model ---
    model: str | None = None                # e.g. "claude-opus-4-6"
    fallback_model: str | None = None

    # --- Session ---
    resume: str | None = None               # Session ID to resume
    fork_session: bool = False              # Fork instead of continue
    continue_conversation: bool = False     # Continue most recent

    # --- Limits ---
    max_turns: int | None = None
    max_budget_usd: float | None = None
    max_thinking_tokens: int | None = None

    # --- Permissions ---
    permission_mode: PermissionMode | None = None  # "default"|"acceptEdits"|"bypassPermissions"|"plan"
    can_use_tool: CanUseTool | None = None  # Runtime permission callback

    # --- MCP ---
    mcp_servers: dict[str, McpServerConfig] | str | Path = {}

    # --- Hooks ---
    hooks: dict[HookEvent, list[HookMatcher]] | None = None

    # --- Subagents ---
    agents: dict[str, AgentDefinition] | None = None

    # --- Working directory ---
    cwd: str | Path | None = None
    add_dirs: list[str | Path] = []         # Additional accessible directories

    # --- Output ---
    output_format: OutputFormat | None = None  # JSON schema for structured output
    include_partial_messages: bool = False

    # --- Environment ---
    env: dict[str, str] = {}
    cli_path: str | Path | None = None
    settings: str | None = None
    setting_sources: list[SettingSource] | None = None  # ["user", "project", "local"]
    plugins: list[SdkPluginConfig] = []
    betas: list[SdkBeta] = []               # e.g. ["context-1m-2025-08-07"]
    sandbox: SandboxSettings | None = None
    user: str | None = None

    # --- Advanced ---
    extra_args: dict[str, str | None] = {}
    max_buffer_size: int | None = None
    stderr: Callable[[str], None] | None = None
    enable_file_checkpointing: bool = False
    permission_prompt_tool_name: str | None = None
```

### System Prompt Configuration

Three patterns:

```python
# 1. Raw custom prompt
options = ClaudeAgentOptions(system_prompt="You are a senior Python developer.")

# 2. Use Claude Code's full system prompt
options = ClaudeAgentOptions(
    system_prompt={"type": "preset", "preset": "claude_code"}
)

# 3. Extend Claude Code's prompt with custom additions
options = ClaudeAgentOptions(
    system_prompt={"type": "preset", "preset": "claude_code", "append": "Always use type hints."}
)
```

### Model Selection

```python
options = ClaudeAgentOptions(
    model="claude-opus-4-6",
    fallback_model="claude-sonnet-4-6"
)
```

Subagents can override the model per-agent with `"sonnet"`, `"opus"`, `"haiku"`, or `"inherit"`.

---

## 4. Tool System

### Built-in Tools

These are the same tools that power Claude Code, executed by the SDK automatically:

| Tool | What It Does |
|------|-------------|
| `Read` | Read any file in the working directory |
| `Write` | Create new files |
| `Edit` | Make precise edits to existing files |
| `Bash` | Run terminal commands, scripts, git operations |
| `Glob` | Find files by pattern (`**/*.ts`, `src/**/*.py`) |
| `Grep` | Search file contents with regex |
| `WebSearch` | Search the web for current information |
| `WebFetch` | Fetch and parse web page content |
| `Task` | Invoke subagents (required for subagent delegation) |
| `AskUserQuestion` | Ask the user clarifying questions with multiple choice options |

### Tool Access Control

```python
options = ClaudeAgentOptions(
    allowed_tools=["Read", "Edit", "Glob", "Grep"],    # Whitelist
    disallowed_tools=["Bash"],                          # Blacklist
)
```

MCP tools use wildcard patterns: `"mcp__github__*"` or `"mcp__db__query"`.

### Custom Tools via In-Process MCP Servers

The SDK provides a `@tool` decorator and `create_sdk_mcp_server()` to define tools as Python functions that run in-process (no subprocess, no IPC overhead):

```python
from claude_agent_sdk import tool, create_sdk_mcp_server, ClaudeSDKClient, ClaudeAgentOptions

@tool("get_weather", "Get current temperature for a location", {"latitude": float, "longitude": float})
async def get_weather(args: dict[str, Any]) -> dict[str, Any]:
    # Your implementation here
    return {"content": [{"type": "text", "text": f"Temperature: 72F"}]}

server = create_sdk_mcp_server(name="my-tools", version="1.0.0", tools=[get_weather])

options = ClaudeAgentOptions(
    mcp_servers={"my-tools": server},
    allowed_tools=["mcp__my-tools__get_weather"],
)
```

**Tool naming convention:** MCP tools are exposed to Claude as `mcp__{server_name}__{tool_name}`.

**Input schema options:**

1. Simple type mapping (recommended): `{"text": str, "count": int, "enabled": bool}`
2. Full JSON Schema: `{"type": "object", "properties": {...}, "required": [...]}`

**Return value format:** Tools must return `{"content": [{"type": "text", "text": "..."}]}`.

### `@tool` Decorator Signature

```python
def tool(
    name: str,
    description: str,
    input_schema: type | dict[str, Any]
) -> Callable[[Callable[[Any], Awaitable[dict[str, Any]]]], SdkMcpTool[Any]]
```

### `create_sdk_mcp_server()` Signature

```python
def create_sdk_mcp_server(
    name: str,
    version: str = "1.0.0",
    tools: list[SdkMcpTool[Any]] | None = None
) -> McpSdkServerConfig
```

### TypeScript Tool Definition (for comparison)

TypeScript uses `zod` schemas for type safety:

```typescript
import { tool, createSdkMcpServer } from "@anthropic-ai/claude-agent-sdk";
import { z } from "zod";

const server = createSdkMcpServer({
  name: "my-tools",
  version: "1.0.0",
  tools: [
    tool("get_weather", "Get temperature", {
      latitude: z.number(),
      longitude: z.number()
    }, async (args) => ({
      content: [{ type: "text", text: `Temperature: ${args.latitude}` }]
    }))
  ]
});
```

---

## 5. Multi-Agent / Handoffs (Subagents)

### Concept

Subagents are separate agent instances spawned by the main agent to handle focused subtasks. They are invoked via the `Task` built-in tool. Three creation methods exist:

1. **Programmatic** -- `agents` parameter in `ClaudeAgentOptions` (recommended for SDK)
2. **Filesystem-based** -- Markdown files in `.claude/agents/` directories
3. **Built-in** -- Claude can always spawn a `general-purpose` subagent when `Task` is in `allowedTools`

### `AgentDefinition` Class

```python
@dataclass
class AgentDefinition:
    description: str                                              # When to use this agent
    prompt: str                                                   # System prompt for the agent
    tools: list[str] | None = None                                # Restricted tools (or inherit all)
    model: Literal["sonnet", "opus", "haiku", "inherit"] | None = None  # Model override
```

### Example -- Multi-Agent Code Review

```python
options = ClaudeAgentOptions(
    allowed_tools=["Read", "Grep", "Glob", "Task"],  # Task tool required!
    agents={
        "code-reviewer": AgentDefinition(
            description="Expert code reviewer for quality and security reviews.",
            prompt="You are a code review specialist...",
            tools=["Read", "Grep", "Glob"],  # Read-only
            model="sonnet",
        ),
        "test-runner": AgentDefinition(
            description="Runs and analyzes test suites.",
            prompt="You are a test execution specialist...",
            tools=["Bash", "Read", "Grep"],  # Can execute
        ),
    },
)
```

### Key Design Decisions

- **Context isolation:** Subagents have their own context windows. Only relevant results flow back to the orchestrator. This prevents information overload.
- **Parallelization:** Multiple subagents can run concurrently.
- **No nesting:** Subagents cannot spawn their own subagents. Do not include `Task` in a subagent's `tools` array.
- **Auto vs. explicit invocation:** Claude automatically matches tasks to subagents based on `description`, or you can force it: `"Use the code-reviewer agent to..."`.
- **Subagent transcripts persist independently** of the main conversation and survive compaction.
- **Resumable:** Subagents can be resumed by capturing `session_id` and `agentId` from the message stream.

### Detecting Subagent Invocation

```python
# Messages from within a subagent include parent_tool_use_id
if hasattr(message, "parent_tool_use_id") and message.parent_tool_use_id:
    print("Running inside subagent")
```

### Common Tool Combinations for Subagents

| Use Case | Tools |
|----------|-------|
| Read-only analysis | `Read`, `Grep`, `Glob` |
| Test execution | `Bash`, `Read`, `Grep` |
| Code modification | `Read`, `Edit`, `Write`, `Grep`, `Glob` |
| Full access | Omit `tools` field (inherits all) |

---

## 6. Guardrails (Hooks)

Hooks intercept agent execution at key lifecycle points. They are the primary mechanism for implementing guardrails, audit logging, input/output validation, and custom security controls.

### Available Hook Events

| Hook Event | Python | TypeScript | Trigger |
|-----------|--------|-----------|---------|
| `PreToolUse` | Yes | Yes | Before tool executes (can block/modify/allow) |
| `PostToolUse` | Yes | Yes | After tool executes (can log/transform) |
| `PostToolUseFailure` | No | Yes | After tool execution failure |
| `UserPromptSubmit` | Yes | Yes | When user submits a prompt |
| `Stop` | Yes | Yes | Agent execution stops |
| `SubagentStop` | Yes | Yes | Subagent completes |
| `PreCompact` | Yes | Yes | Before conversation compaction |
| `SubagentStart` | No | Yes | Subagent initialization |
| `PermissionRequest` | No | Yes | Permission dialog would display |
| `SessionStart` | No | Yes | Session initialization |
| `SessionEnd` | No | Yes | Session termination |
| `Notification` | No | Yes | Agent status messages |

### Hook Architecture

A hook has two parts:
1. **`HookMatcher`** -- Regex pattern matching tool names + callback list + timeout
2. **`HookCallback`** -- The async function that runs

```python
@dataclass
class HookMatcher:
    matcher: str | None = None    # Regex for tool names, e.g. "Bash", "Write|Edit", "^mcp__"
    hooks: list[HookCallback] = []
    timeout: float | None = None  # Seconds (default: 60)
```

### Hook Callback Signature

```python
HookCallback = Callable[
    [dict[str, Any], str | None, HookContext],
    Awaitable[dict[str, Any]]
]
# Arguments: (input_data, tool_use_id, context)
# Returns: dict with optional keys: hookSpecificOutput, systemMessage, continue_, stopReason
```

### PreToolUse Return Values (Guardrail Decisions)

```python
# BLOCK a dangerous operation
return {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "Cannot delete system files",
    }
}

# ALLOW with modified input (redirect to sandbox)
return {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "updatedInput": {**original_input, "file_path": f"/sandbox{path}"},
    }
}

# ALLOW with no changes
return {}
```

### Permission Decision Flow (Priority)

1. **Deny** rules checked first (any match = immediate denial)
2. **Ask** rules checked second
3. **Allow** rules checked third
4. **Default to Ask** if nothing matches

If any hook returns `deny`, the operation is blocked -- other hooks returning `allow` will not override it.

### Example -- Security Guardrail

```python
async def protect_env_files(input_data, tool_use_id, context):
    file_path = input_data["tool_input"].get("file_path", "")
    if file_path.split("/")[-1] == ".env":
        return {
            "hookSpecificOutput": {
                "hookEventName": input_data["hook_event_name"],
                "permissionDecision": "deny",
                "permissionDecisionReason": "Cannot modify .env files",
            }
        }
    return {}

options = ClaudeAgentOptions(
    hooks={
        "PreToolUse": [HookMatcher(matcher="Write|Edit", hooks=[protect_env_files])]
    }
)
```

### Chaining Multiple Hooks

```python
options = ClaudeAgentOptions(
    hooks={
        "PreToolUse": [
            HookMatcher(hooks=[rate_limiter]),          # 1st: rate limits
            HookMatcher(hooks=[authorization_check]),   # 2nd: permissions
            HookMatcher(hooks=[input_sanitizer]),       # 3rd: sanitize
            HookMatcher(hooks=[audit_logger]),          # 4th: log
        ]
    }
)
```

---

## 7. Context and Memory

### Session Management

Sessions maintain conversation context across multiple exchanges:

```python
# Capture session ID from first query
session_id = None
async for message in query(prompt="Read the auth module", options=options):
    if hasattr(message, "subtype") and message.subtype == "init":
        session_id = message.data.get("session_id")

# Resume later with full context
async for message in query(
    prompt="Now find all callers",
    options=ClaudeAgentOptions(resume=session_id),
):
    print(message)
```

### Session Forking

Create branches from a point in conversation history without modifying the original:

```python
options = ClaudeAgentOptions(
    resume=session_id,
    fork_session=True,  # New session ID, original preserved
)
```

### Automatic Context Compaction

When the conversation grows too large for the context window, the SDK automatically compacts (summarizes) earlier messages. Key properties:

- Subagent transcripts are **not** affected by main conversation compaction (stored separately)
- A `PreCompact` hook fires before compaction, allowing you to archive the full transcript
- The compaction trigger can be `"auto"` (token threshold) or `"manual"`

### CLAUDE.md Memory Files

When `setting_sources=["project"]` is set, the SDK loads `CLAUDE.md` (or `.claude/CLAUDE.md`) files as project-level memory/instructions. This is the same mechanism Claude Code uses for persistent project context.

### File Checkpointing

With `enable_file_checkpointing=True`, the SDK tracks file changes and allows rewinding:

```python
await client.rewind_files(user_message_uuid)  # Restore files to earlier state
```

### Skills

Skills are `.claude/skills/SKILL.md` files -- organized folders of instructions, scripts, and resources that Claude loads dynamically to perform specialized tasks. Enabled when `setting_sources=["project"]` is set.

---

## 8. MCP Integration

### Overview

MCP (Model Context Protocol) is the open standard for connecting agents to external tools and data. The SDK supports MCP servers as first-class tool providers, with three transport types:

### Transport Types

| Transport | Configuration | Use Case |
|-----------|--------------|----------|
| **stdio** | `{"command": "npx", "args": [...]}` | Local process servers |
| **SSE** | `{"type": "sse", "url": "https://..."}` | Streaming remote servers |
| **HTTP** | `{"type": "http", "url": "https://..."}` | Non-streaming remote servers |
| **SDK** (in-process) | `create_sdk_mcp_server(...)` | Custom tools in your code |

### Configuration Examples

```python
options = ClaudeAgentOptions(
    mcp_servers={
        # External stdio server
        "github": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env": {"GITHUB_TOKEN": os.environ["GITHUB_TOKEN"]},
        },
        # Remote SSE server
        "remote-api": {
            "type": "sse",
            "url": "https://api.example.com/mcp/sse",
            "headers": {"Authorization": f"Bearer {token}"},
        },
        # In-process SDK server
        "my-tools": custom_sdk_server,
    },
    allowed_tools=[
        "mcp__github__list_issues",      # Specific tool
        "mcp__remote-api__*",            # All tools from server
        "mcp__my-tools__get_weather",    # Specific custom tool
    ],
)
```

### `.mcp.json` Config File

The SDK auto-loads `.mcp.json` from the project root:

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_TOKEN": "${GITHUB_TOKEN}" }
    }
  }
}
```

### MCP Tool Search (Dynamic Loading)

When many MCP tools are configured, tool definitions can consume excessive context. The SDK supports automatic tool search:

- **Auto mode** (default): Activates when MCP tools would consume >10% of the context window
- Tools marked `defer_loading: true` instead of preloaded
- Claude uses a search tool to discover relevant tools on-demand
- Controlled via `ENABLE_TOOL_SEARCH` env var: `"auto"`, `"auto:5"` (custom threshold), `"true"`, `"false"`

### MCP Server Config Types

```python
McpServerConfig = McpStdioServerConfig | McpSSEServerConfig | McpHttpServerConfig | McpSdkServerConfig

class McpStdioServerConfig(TypedDict):
    type: NotRequired[Literal["stdio"]]
    command: str
    args: NotRequired[list[str]]
    env: NotRequired[dict[str, str]]

class McpSSEServerConfig(TypedDict):
    type: Literal["sse"]
    url: str
    headers: NotRequired[dict[str, str]]

class McpHttpServerConfig(TypedDict):
    type: Literal["http"]
    url: str
    headers: NotRequired[dict[str, str]]

class McpSdkServerConfig(TypedDict):
    type: Literal["sdk"]
    name: str
    instance: Any  # MCP Server instance
```

### Error Handling

Check MCP connection status from the `init` system message:

```python
if isinstance(message, SystemMessage) and message.subtype == "init":
    failed = [s for s in message.data.get("mcp_servers", []) if s.get("status") != "connected"]
    if failed:
        print(f"MCP connection failures: {failed}")
```

---

## 9. Permission System (Detail)

### Permission Evaluation Order

When Claude requests a tool, the SDK checks in this order:

1. **Hooks** (`PreToolUse`) -- can allow, deny, or pass through
2. **Permission rules** -- declarative rules in `settings.json` (deny first, then allow, then ask)
3. **Permission mode** -- `bypassPermissions`, `acceptEdits`, `plan`, `default`
4. **`canUseTool` callback** -- runtime programmatic decision

### Permission Modes

| Mode | Behavior |
|------|----------|
| `default` | No auto-approvals; unmatched tools trigger `canUseTool` callback |
| `acceptEdits` | Auto-approves file edits (Edit, Write) and filesystem ops (mkdir, rm, mv, cp) |
| `bypassPermissions` | All tools run without prompts; **propagates to subagents** |
| `plan` | No tool execution; Claude plans without making changes |

### `canUseTool` Callback

```python
CanUseTool = Callable[
    [str, dict[str, Any], ToolPermissionContext],
    Awaitable[PermissionResult]
]

# PermissionResult = PermissionResultAllow | PermissionResultDeny

@dataclass
class PermissionResultAllow:
    behavior: Literal["allow"] = "allow"
    updated_input: dict[str, Any] | None = None      # Modify tool input
    updated_permissions: list[PermissionUpdate] | None = None

@dataclass
class PermissionResultDeny:
    behavior: Literal["deny"] = "deny"
    message: str = ""
    interrupt: bool = False  # Stop execution entirely
```

### Dynamic Permission Mode Changes

```python
q = query(prompt="...", options=ClaudeAgentOptions(permission_mode="default"))
await q.set_permission_mode("acceptEdits")  # Change mid-session
```

---

## 10. Error Handling

```python
from claude_agent_sdk import (
    ClaudeSDKError,        # Base exception
    CLINotFoundError,      # Claude Code CLI not found
    CLIConnectionError,    # Connection to CLI failed
    ProcessError,          # CLI process failed (has exit_code, stderr)
    CLIJSONDecodeError,    # JSON parsing failure (has line, original_error)
)
```

---

## 11. ClaudeSDKClient API (Full-Featured Client)

```python
class ClaudeSDKClient:
    def __init__(self, options: ClaudeAgentOptions | None = None)

    async def connect(self, prompt: str | AsyncIterable[dict] | None = None) -> None
    async def query(self, prompt: str | AsyncIterable[dict], session_id: str = "default") -> None
    async def receive_messages(self) -> AsyncIterator[Message]  # All messages
    async def receive_response(self) -> AsyncIterator[Message]  # Until ResultMessage
    async def interrupt(self) -> None                           # Cancel current operation
    async def rewind_files(self, user_message_uuid: str) -> None  # File checkpointing
    async def disconnect(self) -> None

# Context manager support
async with ClaudeSDKClient(options) as client:
    await client.query("Hello")
    async for msg in client.receive_response():
        print(msg)
```

Key differences from `query()`:
- **Interrupt support** -- stop long-running operations mid-stream
- **Multi-turn** -- maintains context across `query()` calls within the same client
- **Hooks and custom tools** -- only available through this interface
- **Streaming input** -- accepts `AsyncIterable[dict]` for dynamic message generation

---

## 12. Structured Output

```python
options = ClaudeAgentOptions(
    output_format={
        "type": "json_schema",
        "schema": {
            "type": "object",
            "properties": {
                "bugs": {"type": "array", "items": {"type": "string"}},
                "severity": {"type": "string", "enum": ["low", "medium", "high"]}
            },
            "required": ["bugs", "severity"]
        }
    }
)

# Access via ResultMessage.structured_output
```

---

## 13. Comparison: Agent SDK vs. Minimal Custom Agent Loop

### What the Claude Agent SDK Gives You

| Capability | Agent SDK | Custom Loop |
|-----------|-----------|-------------|
| **Tool execution** | Automatic -- built-in Read/Write/Edit/Bash/Glob/Grep/WebSearch/WebFetch | You implement every tool |
| **Agent loop** | Managed by SDK; just consume stream | You write `while stop_reason == "tool_use"` |
| **Context management** | Automatic compaction, session resume/fork | You manage token counting + truncation |
| **MCP integration** | First-class; stdio/SSE/HTTP/in-process transports | You implement MCP client from scratch |
| **Multi-agent** | Built-in subagent system with context isolation | You design delegation/orchestration |
| **Guardrails** | Hook system (PreToolUse/PostToolUse/etc.) | You add checks around your tool dispatch |
| **Permissions** | 4-layer evaluation (hooks -> rules -> mode -> callback) | You implement your own |
| **File checkpointing** | Built-in rewind support | You implement git stash / file backup |
| **Session persistence** | Transcripts saved, resumable across restarts | You serialize/deserialize conversation |
| **Streaming** | Native async iterator with partial message support | You implement SSE parsing |
| **Model fallback** | `fallback_model` config | You implement retry logic |
| **Cost tracking** | `ResultMessage.total_cost_usd`, `usage` | You calculate from API response |
| **Structured output** | JSON schema validation built-in | You post-process and validate |

### Strengths of the Agent SDK

1. **Batteries-included tools** -- Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch all work out of the box. No implementation needed.
2. **Production-ready agent loop** -- The same loop that powers Claude Code, battle-tested at scale.
3. **MCP ecosystem access** -- Connect to hundreds of MCP servers (databases, APIs, browsers) with a few lines of config.
4. **Subagent system** -- Context isolation, parallelization, and specialized agents without building orchestration plumbing.
5. **Hook-based guardrails** -- Composable, chainable security/audit/validation interceptors.
6. **Session management** -- Resume, fork, persistent transcripts, automatic compaction.
7. **Cloud provider flexibility** -- Works with Anthropic API, Bedrock, Vertex AI, Azure.

### Weaknesses / Trade-offs

1. **CLI subprocess dependency** -- The SDK bundles and spawns the Claude Code CLI. This adds process overhead, a Node.js dependency, and makes the agent loop opaque (you cannot inspect or modify the inner loop logic).
2. **Limited loop customization** -- You cannot modify how the agent loop itself works (e.g., custom retry strategies, custom tool result formatting, token budget management). You can only intercept at hook points.
3. **Python/TS hook asymmetry** -- Several hooks (SessionStart, SessionEnd, Notification, PostToolUseFailure, SubagentStart, PermissionRequest) are TypeScript-only.
4. **`query()` limitations** -- The simpler `query()` API does not support hooks, custom tools, or interrupts. You must use `ClaudeSDKClient` for those.
5. **Opaque token management** -- You cannot directly control token counting, prompt assembly, or decide when to compact. The SDK handles this internally.
6. **Cost** -- Built-in tools (especially Bash, file operations) add tokens to every request. A minimal loop can be more token-efficient for narrow use cases.
7. **Vendor lock-in** -- Tightly coupled to Claude models and Anthropic's tool definitions. A minimal loop can be model-agnostic.
8. **Debugging complexity** -- The CLI subprocess makes it harder to debug issues vs. a simple `messages.create()` call.

### When to Use Which

| Scenario | Recommendation |
|----------|---------------|
| Full-featured coding agent | Agent SDK |
| CI/CD automation with file ops | Agent SDK |
| Simple Q&A / chat | Minimal loop or Client SDK |
| Custom tool-heavy workflow | Depends -- Agent SDK if MCP works; minimal loop if you need full control |
| Learning / understanding agent architecture | Minimal loop (forces you to understand every piece) |
| Token-budget-sensitive applications | Minimal loop (fine-grained control) |
| Model-agnostic agent | Minimal loop |
| Production with guardrails/audit needs | Agent SDK (hook system is mature) |

---

## Sources

- [Agent SDK Overview](https://platform.claude.com/docs/en/agent-sdk/overview)
- [Agent SDK Quickstart](https://platform.claude.com/docs/en/agent-sdk/quickstart)
- [Python SDK Reference](https://platform.claude.com/docs/en/agent-sdk/python)
- [Hooks Documentation](https://platform.claude.com/docs/en/agent-sdk/hooks)
- [Subagents Documentation](https://platform.claude.com/docs/en/agent-sdk/subagents)
- [MCP Integration](https://platform.claude.com/docs/en/agent-sdk/mcp)
- [Custom Tools](https://platform.claude.com/docs/en/agent-sdk/custom-tools)
- [Permissions](https://platform.claude.com/docs/en/agent-sdk/permissions)
- [Sessions](https://platform.claude.com/docs/en/agent-sdk/sessions)
- [Python SDK GitHub](https://github.com/anthropics/claude-agent-sdk-python)
- [TypeScript SDK GitHub](https://github.com/anthropics/claude-agent-sdk-typescript)
- [SDK Demos](https://github.com/anthropics/claude-agent-sdk-demos)
- [Building Agents with the Claude Agent SDK](https://claude.com/blog/building-agents-with-the-claude-agent-sdk)

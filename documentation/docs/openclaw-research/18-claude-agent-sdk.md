# Claude Agent SDK

The Claude Agent SDK exposes the same agent loop, tools, and context management that power Claude Code as a programmable Python and TypeScript library.

## Core agent loop

The SDK wraps a **while(tool_call)** loop internally. The `query()` function returns an async iterator that streams messages as the agent works.

```
prompt -> LLM call -> tool calls? -> execute tools -> append results -> repeat
                   -> final output? -> stop
                   -> handoff? -> switch agent -> repeat
```

### Stop conditions

- **`end_turn`**: Model decides the task is complete
- **`max_turns`**: Configurable turn limit
- **`max_budget_usd`**: Dollar-denominated budget cap
- **Interrupt**: `ClaudeSDKClient.interrupt()` halts mid-stream
- **Hook-driven stop**: A `Stop` hook returns `continue_: False`
- **Compaction pause**: API returns `stop_reason: "compaction"` after summarizing context
- **Error**: A `ResultMessage` with `subtype="error_during_execution"`

### Message flow

Messages follow a typed union: `UserMessage | AssistantMessage | SystemMessage | ResultMessage | StreamEvent`. First message is always a `SystemMessage` with `subtype="init"` (session ID, tools, MCP status). Final message is a `ResultMessage` with cost, duration, and turn count.

## Two client models

| Feature | `query()` | `ClaudeSDKClient` |
|---------|-----------|-------------------|
| Session | New each call | Persistent |
| Conversation continuity | Via `resume` param | Built-in |
| Interrupts | No | Yes |
| Hooks | No | Yes |
| Custom MCP tools | No | Yes |
| Multi-turn | Requires session IDs | Natural |

## Tool system

### Built-in tools (execute without developer implementation)

| Tool | Purpose |
|------|---------|
| `Read` | Read files (text, images, PDFs, notebooks) |
| `Write` | Create new files |
| `Edit` | Precise string replacement edits |
| `Bash` | Execute terminal commands |
| `Glob` | Pattern-based file search |
| `Grep` | Regex content search |
| `WebSearch` | Web search with domain filtering |
| `WebFetch` | Fetch and AI-process web content |
| `Task` | Invoke subagents |
| `AskUserQuestion` | Structured clarifying questions |
| `TodoWrite` | Task tracking |
| `NotebookEdit` | Jupyter cell editing |

### Custom tools via MCP

Tools defined using Model Context Protocol as in-process SDK MCP servers:

```python
@tool("get_weather", "Get temperature", {"latitude": float, "longitude": float})
async def get_weather(args):
    return {"content": [{"type": "text", "text": f"Temperature: {temp}"}]}

server = create_sdk_mcp_server(name="my-tools", version="1.0.0", tools=[get_weather])
```

MCP transports: **stdio** (local processes), **SSE** (streaming remote), **HTTP** (remote APIs), **SDK** (in-process).

Tool search activates automatically when >10% of context is consumed by tool definitions — uses `defer_loading: true` so only relevant tools load on demand.

### Permission flow

Evaluated in order: Hooks (`PreToolUse`) -> Permission rules (deny > allow > ask) -> Permission mode -> `can_use_tool` callback. Deny always wins.

## Context management

### Automatic compaction

Summarizes previous messages when approaching context limits. A `PreCompact` hook fires before compaction. Subagent transcripts are unaffected.

### Context engineering for long-running agents

Recommended multi-session pattern:
1. **Initializer agent**: Sets up environment with all necessary context
2. **Coding agent**: Makes incremental progress, leaving clean artifacts (`claude-progress.txt`, git commits, feature list JSON)
3. **Session startup protocol**: Each session reads progress docs, reviews features, runs tests before starting work

## Multi-agent (subagents)

Invoked via the `Task` tool. Three creation methods:
- **Programmatic**: `AgentDefinition` objects in `agents` parameter
- **Filesystem**: Markdown in `.claude/agents/`
- **Built-in**: General-purpose agent always available

Key properties:
- **Context isolation**: Separate context from main agent
- **Parallelization**: Multiple subagents run concurrently
- **Tool restrictions**: Per-subagent tool allowlists
- **Model flexibility**: Per-subagent model (`sonnet`, `opus`, `haiku`, `inherit`)
- **No recursion**: Subagents cannot spawn their own subagents
- **Resumable**: Captured `agentId` can resume later

## Session persistence

- **Session ID**: Auto-generated, returned in init message
- **Resume**: `resume=session_id` continues a previous session
- **Fork**: `fork_session=True` branches without modifying original
- **File checkpointing**: `enable_file_checkpointing=True` tracks file changes; `rewind_files(uuid)` restores state

## Security model

### Sandbox settings

```python
SandboxSettings = {
    "enabled": True,
    "autoAllowBashIfSandboxed": True,
    "network": {"allowLocalBinding": True, "httpProxyPort": 8080},
}
```

### Permission modes

| Mode | Behavior |
|------|----------|
| `default` | No auto-approvals |
| `acceptEdits` | Auto-approves file operations |
| `bypassPermissions` | All tools run without prompts; inherits to subagents |
| `plan` | No tool execution; planning only |

## Streaming

Two input modes:
- **Streaming** (recommended): Async generator yields messages, supports images, interrupts, hooks, MCP
- **Single message**: Simple string prompt, no hooks/interrupts/MCP

`include_partial_messages=True` yields `StreamEvent` objects with raw API stream events.

## Model support

Direct model config with fallback:
```python
ClaudeAgentOptions(model="claude-opus-4-6", fallback_model="claude-sonnet-4-5")
```

Providers via environment variables: Anthropic API, Amazon Bedrock, Google Vertex AI, Microsoft Azure.

## Architectural insight

The SDK is **Claude Code exposed as a library** — it wraps the same CLI binary, system prompt, tool implementations, and session infrastructure. The Python/TypeScript SDKs communicate with the Claude Code CLI via JSON over stdin/stdout (hence `CLINotFoundError` and `cli_path` config).

## Key references

- [Agent SDK overview](https://platform.claude.com/docs/en/agent-sdk/overview)
- [Python SDK reference](https://platform.claude.com/docs/en/agent-sdk/python)
- [Building agents (blog)](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk)
- [Effective harnesses (blog)](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [GitHub: claude-agent-sdk-python](https://github.com/anthropics/claude-agent-sdk-python)

# OpenHands Agent Loop Architecture

## 1. Overview

**OpenHands** (formerly OpenDevin) is an open-source autonomous AI software engineering platform capable of executing complex engineering tasks and collaborating actively with users on software development projects. It creates and deploys generalist AI agents that can modify code, run commands, browse the web, and call APIs -- behaving as an AI pair programmer with full environment access.

| Property | Value |
|----------|-------|
| **Language** | Python (77.2%), TypeScript (19.9%) |
| **Repository** | https://github.com/OpenHands/OpenHands (previously All-Hands-AI/OpenHands) |
| **Documentation** | https://docs.openhands.dev/ |
| **License** | MIT (except `enterprise/` directory, which is source-available) |
| **Python version** | 3.12 (3.13/3.14 support planned) |
| **Stars** | 65,800+ |
| **Contributors** | 441+ |
| **SDK repo** | https://github.com/OpenHands/software-agent-sdk |
| **Paper** | [ICLR 2025](https://openreview.net/pdf/95990590797cff8b93c33af989ecf4ac58bde9bb.pdf) |

### Evolution from OpenDevin

The project began as **OpenDevin**, an open-source alternative to Cognition's Devin AI. It was renamed to **OpenHands** to establish its own identity as a broader platform. The architecture has undergone two major generations:

- **V0 (monolithic):** Tightly coupled agent core, evaluation, and application code. Mandatory sandbox assumption created friction for local workflows. Configuration sprawled across 140+ fields, 15 classes, and 2,800+ lines. Divergent code paths for sandbox vs. local execution.
- **V1 (modular SDK):** Complete architectural redesign into four composable packages. Optional sandboxing, stateless agent components, event-sourced state management, and typed tool system with MCP integration.

### Core philosophy

1. **Open and transparent.** MIT license, community-driven development, full visibility into AI decisions. No vendor lock-in.
2. **Sandboxed execution.** Agents run in isolated Docker containers by default, so arbitrary code execution does not risk the host system.
3. **Multi-agent delegation.** Agents can delegate subtasks to specialized agents (browsing, verification, etc.).
4. **Unified code action space.** The primary agent (CodeActAgent) consolidates all actions into code execution -- bash commands, Python cells, and browser automation -- rather than maintaining separate action types.
5. **Event-sourced architecture.** All state flows through an append-only event stream, enabling replay, persistence, and deterministic state reconstruction.

### Tech stack and key dependencies

- **LiteLLM** -- unified LLM provider abstraction (100+ providers: OpenAI, Anthropic, Google, Azure, AWS Bedrock, local models)
- **Docker** -- sandboxed runtime execution (default)
- **FastMCP** -- MCP tool integration
- **Pydantic** -- configuration and event serialization (discriminated unions)
- **React** (frontend SPA) + REST API + WebSocket (server)
- **Poetry** -- dependency management

### Repository structure (V1 SDK)

```
openhands/
  sdk/                    # Core SDK: Agent, Conversation, LLM, Tool, MCP
    agent/                # Agent class, AgentBase, step() logic
    event/                # Event types, EventLog, LLMConvertibleEvent
    llm/                  # LLM abstraction, LiteLLM wrapper
    tool/                 # ToolDefinition, ToolExecutor, MCPToolDefinition
    condenser/            # Context condensation (LLMSummarizingCondenser)
    security/             # SecurityAnalyzer, ConfirmationPolicy
  tools/                  # Concrete tool implementations
  workspace/              # Execution environments (Docker, hosted APIs)
  agent_server/           # REST/WebSocket API server

openhands/ (V0, still in main repo)
  agenthub/               # Agent implementations (CodeActAgent, BrowsingAgent, etc.)
  controller/             # AgentController, StuckDetector
  events/                 # Event classes (Action, Observation subtypes)
  runtime/                # Runtime implementations (Docker, Local, Remote)
    impl/
      docker/             # docker_runtime.py
      local/              # local_runtime.py
      remote/             # remote_runtime.py
    plugins/              # Jupyter, VSCode, AgentSkills plugins
    utils/                # runtime_build.py (image tagging)
  llm/                    # llm.py (LiteLLM wrapper)
  server/                 # Session, ConversationManager
  storage/                # Persistence layer
  core/config/            # sandbox_config.py and others
  security/               # Security analyzer implementations
```

---

## 2. Agent loop lifecycle

### The AgentController

The `AgentController` (in `openhands/controller/agent_controller.py`) is the central orchestrator. It:

1. **Initializes** the Agent, manages `State`, and subscribes to the `EventStream`.
2. **Drives the main loop** step by step, calling `agent.step(state)` each iteration.
3. **Manages lifecycle transitions:** INIT -> RUNNING -> PAUSED/AWAITING_USER_INPUT -> FINISHED/ERROR/STOPPED.
4. **Enforces safety limits:** `max_iterations`, budget checks, and stuck-loop detection.

### The step cycle

Each iteration of the agent loop follows this pattern:

```
1. AgentController._step() is called
2. Check delegation state (is a sub-agent running?)
3. Check budget / iteration limits
4. Check state (is agent paused, waiting for user?)
5. Run StuckDetector to check for infinite loops
6. Call agent.step(state) -> returns an Action
7. SecurityAnalyzer evaluates the Action's risk level
8. If confirmation required, pause and wait for user approval
9. Execute the Action through the Runtime -> produces an Observation
10. Publish the Observation to the EventStream
11. Update State (increment iteration counter, store events)
12. Repeat
```

### State management

The `State` object represents the agent's task status:

- **Current step/iteration counters** (global and local)
- **Recent event history** accessible to the agent
- **Long-term planning context**
- **Delegation tracking** (subtask hierarchy depth)

In V1, `ConversationState` is the single mutable entity, maintaining metadata fields and an append-only `EventLog`. A FIFO lock ensures thread-safety. Persistence uses a dual-path design: `base_state.json` for metadata and individual JSON files per event.

### StuckDetector

Located at `openhands/controller/stuck.py`, the `StuckDetector` monitors for infinite loops:

- Detects repeated identical actions (e.g., the same command run 3+ times)
- Raises `AgentStuckInLoopError` to halt execution
- Known challenge: false positives when agents legitimately poll long-running processes (e.g., sending empty `CmdRunAction` to check on a background build)

### Session architecture

Each user task creates a **Session** containing:
- One `EventStream`
- One `AgentController`
- One `Runtime`

The `ConversationManager` routes requests to the correct Session and maintains the active session list.

---

## 3. Event stream architecture

### EventStream class

The `EventStream` is the central communication hub using a **publish-subscribe** pattern. Any component (agent, user, runtime, controller) can:
- **Publish** events to the stream
- **Subscribe** to events via `EventStreamSubscriber` interface

Events are append-only and immutable once published. The stream supports:
- Type-safe event filtering (using `type[Event]` class references, not strings)
- Thread-safe concurrent access
- Persistence to file storage
- Event replay for state reconstruction

### Event hierarchy (V1 SDK)

```
Event (base)
  |-- LLMConvertibleEvent (visible to LLM, has to_llm_message())
  |     |-- MessageEvent          # Agent or user text communication
  |     |-- ActionEvent           # Agent tool invocation
  |     |-- SystemPromptEvent     # System instructions with optional dynamic context
  |     |-- ObservationBaseEvent
  |           |-- ObservationEvent # Tool execution result (linked via action_id)
  |           |-- UserRejectObservation # User blocked an action
  |
  |-- Internal Events (not visible to LLM)
        |-- ConversationStateUpdateEvent  # WebSocket state sync
        |-- CondensationEvent             # Summary replacing dropped events
        |-- CondensationRequest           # Request to trigger summarization
```

### Event types -- Actions (V0)

| Action class | Purpose |
|---|---|
| `CmdRunAction` | Execute shell command (supports background, stdin, timeout) |
| `FileEditAction` | Edit file content (produces git-patch-format observation) |
| `FileReadAction` | Read file contents |
| `FileWriteAction` | Write file contents |
| `IPythonRunCellAction` | Execute Python code in Jupyter kernel |
| `BrowseInteractiveAction` | Programmatic browser interaction |
| `BrowseURLAction` | Navigate to a URL |
| `AgentDelegateAction` | Delegate subtask to another agent |
| `MessageAction` | Send message to user |
| `TaskTrackingAction` | Track task progress |
| `MCPAction` | Execute an MCP tool |
| `AgentFinishAction` | Signal task completion |

### Event types -- Observations (V0)

| Observation class | Purpose |
|---|---|
| `CmdOutputObservation` | Shell command output |
| `FileReadObservation` | File contents |
| `FileEditObservation` | Edit result (git patch format) |
| `ErrorObservation` | Error message |
| `NullObservation` | No output (action completed silently) |
| `UserRejectObservation` | User rejected a proposed action |
| `TaskTrackingObservation` | Task tracking result |

### ConversationMemory

`ConversationMemory` processes the event history into a coherent conversation for the LLM:
- Converts `Action` and `Observation` events into `Message` objects with proper roles
- Separates consecutive user messages with double newlines
- Filters unmatched tool calls to prevent LLM errors
- Applies prompt caching markers for providers that support it

---

## 4. Runtime and sandboxing

### Architecture overview

OpenHands uses a **client-server architecture** for code execution. The Runtime is responsible for executing Actions and returning Observations.

```
 Backend (Host)                    Docker Container
+------------------+              +-------------------+
| AgentController  |   REST API   | ActionExecutor    |
| EventStream      | <==========> | Bash Shell        |
| Runtime Client   |              | Jupyter Kernel    |
+------------------+              | Plugin System     |
                                  +-------------------+
```

### Docker Runtime (default)

Located at `openhands/runtime/impl/docker/docker_runtime.py`:

1. **Image building:** Takes user's base Docker image and extends it with an "OH runtime image" containing the OpenHands runtime client code.
2. **Container launch:** Starts the OH runtime image as a Docker container.
3. **ActionExecutor initialization:** Inside the container, `ActionExecutor` sets up a bash shell and loads plugins.
4. **RESTful communication:** The backend sends Actions via REST API; the container executes them and returns Observations.

**Three-tier image tagging** (in `openhands/runtime/utils/runtime_build.py`):
- **Source tag:** `oh_v{version}_{16-digit-source-hash}` -- most specific, represents current source
- **Lock tag:** `oh_v{version}_{16-digit-lock-hash}` -- captures dependencies
- **Versioned tag:** `oh_v{version}_{base_image}` -- generic version reference

**Build strategies** (fastest to slowest):
1. No rebuild (source tag exists)
2. Fast rebuild (lock tag exists, only source layer rebuilt)
3. Standard rebuild (versioned tag exists, dependencies cached)
4. Full rebuild (from base image)

### Sandbox types

| Type | Config | Description |
|---|---|---|
| **Docker** | `RUNTIME=docker` | Default. Runs agent server inside a Docker container. Strong isolation. |
| **Process** | `RUNTIME=process` | Runs agent server as a regular process. No isolation. Faster. Useful for CI. |
| **Remote** | `RUNTIME=remote` | Runs agent server in a remote managed environment. For hosted deployments. |
| **E2B** | (integration) | Open-source sandbox using Firecracker microVMs. Starts in <200ms. |

### File system access

Volume mounting supports two approaches:
- **Bind mounts:** `/abs/host/path:/container/path[:mode]`
- **Named volumes:** `volume:<name>:/container/path[:mode]`
- **Overlay mode:** Copy-on-write layers via `:overlay` suffix. Requires `SANDBOX_VOLUME_OVERLAYS` env var pointing to a writable host directory.

Configuration: `openhands/core/config/sandbox_config.py`

### Security model

The sandboxed approach provides:
- **Process isolation:** Container prevents host system access
- **Resource control:** Docker limits prevent runaway processes
- **Reproducibility:** Controlled, consistent environments
- **Network control:** Configurable port allocation with file-locked ranges

Port management uses `find_available_port_with_lock` for stable concurrent allocation across main runtime port, VSCode port, and application plugin ports.

### Plugin system

Plugins extend runtime capabilities via a registration-based architecture:

| Plugin | Location | Purpose |
|---|---|---|
| `JupyterPlugin` | `openhands/runtime/plugins/jupyter/` | IPython/Jupyter Kernel Gateway |
| `VSCodePlugin` | `openhands/runtime/plugins/vscode/` | VS Code server with tokenized URLs |
| `AgentSkillsPlugin` | `openhands/runtime/plugins/agent_skills/` | Pre-built agent capabilities |

- **Base class:** `Plugin`
- **Registry:** `ALL_PLUGINS` in `openhands/runtime/plugins/__init__.py`
- **Configuration:** `Agent.sandbox_plugins: list[PluginRequirement]`
- **Lifecycle:** Plugins initialize asynchronously at runtime startup

---

## 5. Agent types

### AgentHub

Located in `openhands/agenthub/`, agents are registered implementations. Every agent implements a `step()` method that receives a `State` object and returns an `Action`.

All agents access `self.llm` for language model interaction via LiteLLM.

### CodeActAgent (primary)

The default and most capable agent. Based on the [CodeAct framework](https://arxiv.org/abs/2402.01030) by Xingyao Wang et al.

**Philosophy:** Consolidate all LLM actions into a unified code action space. Rather than separate action types, everything flows through code execution.

**Tools (via function calling interface using `ChatCompletionToolParam`):**

| Tool | Purpose |
|---|---|
| `execute_bash` | Execute Linux bash commands. Supports background processes, stdin input, timeout, output redirection. |
| `execute_ipython_cell` | Run Python code in IPython. Variables persist across cells. Supports `%pip` magic. |
| `str_replace_editor` | String-based file manipulation with line-numbered viewing, undo, and persistent state. |
| `edit_file` | LLM-based file editing with partial file and append modes. |
| `web_read` | Convert webpage content to markdown. |
| `browser` | Programmatic browser interaction: navigation, clicking, form filling, scrolling, file uploads, drag-and-drop. |

**Configuration options:**
- `enable_browsing`: Toggle web interaction tools
- `enable_jupyter`: Toggle IPython execution
- `enable_llm_editor`: Use LLM-based editing (falls back to `str_replace_editor` if disabled)

**Two interaction modes:**
1. **Conversation:** Natural language for clarification, confirmation, status updates.
2. **Code execution:** Tool invocation via the unified code interface.

### BrowsingAgent

A specialized web agent focused on browsing and information retrieval. Used as a building block for web-related subtasks. Typically invoked via delegation from CodeActAgent when a task requires web research.

### VisualBrowsingAgent

Handles visual web content with screenshot-based interaction. Uses Set-of-Mark (SoM) visual browsing when `enable_som_visual_browsing` is enabled.

### DelegatorAgent

A meta-agent that forwards tasks to specialized micro-agents:
- `RepoStudyAgent` -- study a repository's structure
- `VerifierAgent` -- verify task completion

### Other agents

- `ReadOnlyAgent` -- limited-capability variant for read-only tasks
- `LocAgent` -- specialized localization agent
- `DummyAgent` -- testing/reference implementation

### Multi-agent delegation

Delegation is a first-class concept:
- `AgentDelegateAction` triggers a sub-agent to handle a specific subtask
- Delegation depth is tracked via hierarchy levels
- Each sub-agent gets its own conversation context (a "subtask")
- The parent agent resumes when the sub-agent finishes or errors

In V1, sub-agent delegation is implemented as a standard tool rather than core logic, making it extensible.

---

## 6. Tool/action system

### V0: Action-Observation pattern

Every tool interaction follows the same contract:
1. **Agent** produces an `Action` (e.g., `CmdRunAction(command="ls -la")`)
2. **Runtime** executes the action in the sandbox
3. **Runtime** returns an `Observation` (e.g., `CmdOutputObservation(content="...")`)
4. **EventStream** records both events

### V1 SDK: Typed tool system

The V1 SDK introduces a strict **Action-Execution-Observation** contract:

```python
# Action: Input schema validated via Pydantic
class CmdRunAction(BaseModel):
    command: str
    timeout: int = 120
    blocking: bool = True

# ToolExecutor: Implements the actual logic
class CmdRunExecutor:
    def execute(self, action: CmdRunAction) -> CmdOutputObservation: ...

# Observation: Structured output for LLM consumption
class CmdOutputObservation(BaseModel):
    content: str
    exit_code: int
```

**ToolDefinition** unifies native and MCP tools:
- `MCPToolDefinition` extends `ToolDefinition` by translating MCP JSON schemas into Action models
- `MCPToolExecutor` delegates execution to FastMCP's `MCPClient`
- External MCP tools behave identically to native tools at runtime

**Tool registration:** Registry-based mechanism decouples specifications from implementations. Tool specs are pure JSON that can cross process/network boundaries. Lazy instantiation happens based on execution context.

### Non-function-calling model support

`NonNativeToolCallingMixin` converts tool schemas to text prompts and parses tool calls via regex, enabling models without native function calling to use the same tool definitions.

### How CodeActAgent selects actions

1. The agent's `step()` method builds a prompt from the current State (event history).
2. The prompt includes tool definitions in `ChatCompletionToolParam` format.
3. The LLM responds with either:
   - A **tool call** (function name + JSON arguments) -> converted to an `ActionEvent`
   - A **text message** -> converted to a `MessageEvent`
4. Tool calls are validated against the Pydantic action schema before execution.
5. The SecurityAnalyzer evaluates risk before the Runtime executes.

---

## 7. Memory and context management

### Conversation history

The `EventStream` maintains the complete history of all events. The `ConversationMemory` component converts this into LLM-consumable messages:

1. **Action events** become assistant messages (tool calls)
2. **Observation events** become tool-result messages
3. **Message events** become user or assistant messages
4. Unmatched tool calls are filtered to prevent LLM errors
5. Consecutive user messages are separated by double newlines

### Context condensation

When conversations grow beyond token limits, the **Condenser** system compresses history while preserving essential context.

**Default implementation:** `LLMSummarizingCondenser`

```python
LLMSummarizingCondenser(
    llm=condenser_llm,    # Separate LLM instance (can use cheaper model)
    max_size=10,           # Trigger threshold (event count)
    keep_first=2           # Events always preserved (system prompt, initial message)
)
```

**How it works:**
1. **Preserve recent exchanges** -- most recent messages stay unchanged for immediate context
2. **Retain critical information** -- user goals, technical specs, critical file paths, failing tests
3. **Condense earlier content** -- older portions summarized via LLM call
4. **Maintain continuity** -- agent retains awareness of past progress without processing full history

**Results are stored as `CondensationEvent`** in the event log. Before sending history to the LLM, condensation events replace the dropped entries with summaries. The full event log is preserved regardless of condensation (condensation is a view layer, not destructive).

**Performance benchmarks (SWE-bench Verified):**
- Condensed: 54% solve rate (average)
- Baseline (no condensation): 53% solve rate
- Up to **2x per-turn API cost reduction**
- Baseline scales **quadratically** over time; condensed scales **linearly**
- Condensation triggers only at thresholds, balancing context management with prompt cache efficiency

### Prompt caching

For providers supporting prompt caching (Anthropic, etc.), the system marks specific messages as cacheable:
- Last content item of the system message
- Last content item of the final user or tool message

This maximizes cache hits while minimizing cache write cost.

### Microagent knowledge

Three-tier knowledge retrieval system:
1. **Global microagents** from `skills/` directory
2. **User microagents** from `~/.openhands/microagents/`
3. **Workspace microagents** from cloned repositories

Knowledge microagents activate when keywords appear in user or agent messages. Two recall types:
- `WORKSPACE_CONTEXT`: Triggered on first user message, initializes with repo info and runtime details
- `KNOWLEDGE`: Triggered during conversation to retrieve relevant microagent knowledge

Configuration via `AgentConfig`:
- `enable_prompt_extensions`: Enable/disable microagent recall (default: `True`)
- `disabled_microagents`: List of microagent names to exclude

---

## 8. LLM integration

### LLM class

The `LLM` class (Pydantic config model) wraps LiteLLM and handles:
- Provider configuration and credential management
- Request orchestration with retry and timeout
- Cost tracking and telemetry
- Streaming support

**Key methods:**
- `completion()` -- Chat Completions API with retry, timeout, streaming
- `responses()` -- OpenAI Responses API for enhanced reasoning (encrypted thinking, reasoning summaries)
- `load_from_env()` / `load_from_json()` -- configuration hydration

### Configuration

```python
LLM(
    model="anthropic/claude-sonnet-4.1",  # Provider/model identifier
    api_key=SecretStr("..."),             # Secure credential storage
    temperature=0.0,                      # Randomness control
    timeout=120,                          # Request timeout (seconds)
    num_retries=3,                        # Retry attempts
    input_cost_per_token=0.003,           # Custom pricing (optional)
    output_cost_per_token=0.015,          # Custom pricing (optional)
)
```

Environment variables follow the pattern `LLM_FIELD` (e.g., `LLM_MODEL`, `LLM_API_KEY`).

### Retry and error handling

- **Exponential backoff** on failures with configurable retry count
- **Normalized error codes** through LiteLLM abstraction (provider-specific errors mapped to standard codes)
- **Validation** of required fields (model, messages) before sending
- Automatic failure recovery up to retry limit

### Cost tracking and telemetry

Automatic metrics collection per request:
- Token counts (input/output separately)
- Per-request USD cost calculation
- Latency in milliseconds
- Error tracking with retry counts
- LiteLLM includes cost data for major providers; custom models support override pricing

### Multi-LLM routing

`RouterLLM` subclass enables selecting different models per request based on custom logic (e.g., routing multimodal requests to vision-capable models, using cheaper models for condensation).

### Model feature detection

`model_features.py` uses pattern matching to auto-detect model capabilities, routing supported models (e.g., GPT-5 variants) to the Responses API path automatically.

### Provider support

LiteLLM enables 100+ providers: OpenAI, Anthropic, Google (Gemini/Vertex), Azure OpenAI, AWS Bedrock, Cohere, Mistral, HuggingFace, NVIDIA NIM, local models via Ollama/LM Studio, and many more. Custom providers use prefix notation: `lm_studio/model-name` with a `base_url` setting.

---

## 9. Security and confirmation

### Two-layer security model

1. **SecurityAnalyzer** -- evaluates action risk before execution
2. **ConfirmationPolicy** -- determines whether user approval is needed

These are decoupled: risk assessment is separate from enforcement.

### Risk levels

| Level | Description | Example |
|---|---|---|
| `LOW` | Safe operations, minimal impact | File viewing, reading |
| `MEDIUM` | Moderate impact, review recommended | File modifications |
| `HIGH` | Significant impact, requires confirmation | Destructive commands, network operations |
| `UNKNOWN` | Risk could not be determined | Novel or ambiguous actions |

### SecurityAnalyzer

- **`LLMSecurityAnalyzer`** (default): Appends a `security_risk` field to tool calls. The LLM annotates actions with risk levels during generation.
- Custom analyzers extend `SecurityAnalyzerBase` and override `security_risk()`.
- Agents accept Jinja2 template files via `security_policy_filename` for custom organizational risk guidelines.

### Confirmation policies

| Policy | Behavior |
|---|---|
| `AlwaysConfirm()` | Requires approval for every action |
| `NeverConfirm()` | Executes all actions automatically |
| `ConfirmRisky()` | Requires approval only for HIGH-risk actions (default threshold) |

When pending actions await approval, the conversation enters `WAITING_FOR_CONFIRMATION` status. Users can reject with feedback: `conversation.reject_pending_actions("reason")`.

---

## 10. Comparison notes: OpenHands vs. minimal custom agent loop

### Key strengths of OpenHands

1. **Sandboxed execution is the standout feature.** Docker-based isolation means agents can run arbitrary shell commands, install packages, modify files, and execute code without risking the host. This is the single biggest differentiator from a minimal agent loop that runs directly on the host machine.

2. **Production-grade infrastructure.** Session management, WebSocket streaming, REST API, cost tracking, telemetry, file persistence, multi-user support -- all built in.

3. **Multi-agent delegation.** Agents can spawn sub-agents for specialized tasks (browsing, verification, repo study). A minimal loop typically runs a single agent.

4. **Context condensation at scale.** The `LLMSummarizingCondenser` handles arbitrarily long sessions with linear cost scaling, validated on SWE-bench with no performance degradation.

5. **Rich tool ecosystem.** Bash, IPython, file editing (string replacement and LLM-based), web browsing, MCP integration, VS Code, Jupyter -- all available out of the box.

6. **Security model.** Risk analysis + confirmation policies provide guardrails for autonomous execution. Critical for production deployments.

7. **Event-sourced state.** Full replay capability, deterministic state reconstruction, and clean separation of concerns via the EventStream.

8. **Broad LLM support.** 100+ providers via LiteLLM with automatic capability detection, cost tracking, and multi-model routing.

### Key weaknesses / tradeoffs

1. **Heavyweight.** Requires Docker, has a large dependency tree, complex configuration, and significant memory/CPU overhead. A minimal agent loop can start in milliseconds with zero infrastructure.

2. **Complexity.** Nine interlocking SDK components, multiple runtime types, plugin systems, microagent knowledge systems -- significant learning curve and maintenance burden.

3. **Docker dependency.** The default (and recommended) runtime requires Docker. The local/process runtime exists but is marked "unsafe." This is a barrier for environments where Docker is unavailable or impractical.

4. **Latency.** Every action crosses a REST API boundary to the Docker container and back. A minimal loop executes tools in-process with zero serialization overhead.

5. **Stuck detection challenges.** The `StuckDetector` has known false-positive issues with long-running processes. Agents polling a build get killed as "stuck in a loop."

6. **Configuration sprawl.** Even V1's simplification still requires understanding multiple packages, environment variables, TOML config, and Jinja2 templates.

### Lessons for a minimal agent loop

| OpenHands concept | Minimal loop adaptation |
|---|---|
| EventStream (append-only event log) | Even a minimal loop benefits from structured event logging for debugging and replay |
| Context condensation | Essential for long sessions; LLM-summarizing approach is proven effective |
| Action-Observation contract | Clean separation between "what to do" and "what happened" makes the loop extensible |
| Security risk levels | Even without full SecurityAnalyzer, categorizing actions as safe/dangerous prevents accidents |
| Prompt caching markers | Marking cacheable message boundaries reduces costs significantly |
| StuckDetector | Simple repetition detection prevents runaway loops and wasted tokens |
| Sandbox isolation | The biggest feature gap in a minimal loop; consider optional Docker/subprocess isolation |
| MCP tool integration | First-class MCP support makes the tool system immediately extensible |

### Architecture comparison

```
OpenHands:                              Minimal Agent Loop:
+------------------+                    +------------------+
| React Frontend   |                    | CLI / stdin      |
+--------+---------+                    +--------+---------+
         |                                       |
+--------+---------+                    +--------+---------+
| REST/WS Server   |                    | (none)           |
| ConversationMgr  |                    |                  |
+--------+---------+                    +--------+---------+
         |                                       |
+--------+---------+                    +--------+---------+
| AgentController  |                    | agent_loop()     |
| EventStream      |                    | message list     |
| State            |                    | simple state     |
+--------+---------+                    +--------+---------+
         |                                       |
+--------+---------+                    +--------+---------+
| Agent.step()     |                    | llm_client.chat()|
| LLM (LiteLLM)   |                    | anthropic SDK    |
+--------+---------+                    +--------+---------+
         |                                       |
+--------+---------+                    +--------+---------+
| Docker Runtime   |                    | subprocess.run() |
| ActionExecutor   |                    | direct file I/O  |
| REST API bridge  |                    | in-process exec  |
+------------------+                    +------------------+
```

The fundamental tradeoff: OpenHands provides industrial-strength sandboxing, multi-agent coordination, and production infrastructure at the cost of complexity and overhead. A minimal agent loop provides simplicity, speed, and transparency at the cost of safety guarantees and scalability.

---

## Sources

- [OpenHands GitHub Repository](https://github.com/OpenHands/OpenHands)
- [OpenHands Documentation](https://docs.openhands.dev/)
- [OpenHands SDK Documentation](https://docs.openhands.dev/sdk)
- [OpenHands Architecture README](https://github.com/All-Hands-AI/OpenHands/blob/main/openhands/README.md)
- [Runtime Architecture Docs](https://docs.openhands.dev/openhands/usage/architecture/runtime)
- [Agent Docs](https://docs.openhands.dev/sdk/arch/agent)
- [LLM Architecture Docs](https://docs.openhands.dev/sdk/arch/llm)
- [Event System API Reference](https://docs.openhands.dev/sdk/api-reference/openhands.sdk.event)
- [Context Condenser Guide](https://docs.openhands.dev/sdk/guides/context-condenser)
- [Security Guide](https://docs.openhands.dev/sdk/guides/security)
- [CodeActAgent README](https://github.com/OpenHands/OpenHands/blob/main/openhands/agenthub/codeact_agent/README.md)
- [Agenthub README](https://github.com/All-Hands-AI/OpenHands/blob/main/openhands/agenthub/README.md)
- [Runtime Overview](https://docs.openhands.dev/openhands/usage/runtimes/overview)
- [Context Condensation Blog Post](https://openhands.dev/blog/openhands-context-condensensation-for-more-efficient-ai-agents)
- [The Path to OpenHands V1 Blog Post](https://openhands.dev/blog/the-path-to-openhands-v1)
- [OpenHands Software Agent SDK Paper (arXiv:2511.03690)](https://arxiv.org/html/2511.03690v1)
- [OpenHands ICLR 2025 Paper](https://openreview.net/pdf/95990590797cff8b93c33af989ecf4ac58bde9bb.pdf)
- [Agent Types Documentation](https://docs.openhands.dev/openhands/usage/agents)
- [Software Agent SDK Repository](https://github.com/OpenHands/software-agent-sdk)
- [DeepWiki: Memory and Context Management](https://deepwiki.com/OpenHands/OpenHands/6.3-agent-configuration)

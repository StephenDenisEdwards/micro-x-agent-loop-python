# Human-in-the-Loop: LLM-Initiated User Questioning in Agent Loops

**Date:** 2026-03-04
**Status:** Research Complete
**Purpose:** Investigate how agent systems allow the LLM to pose questions to the user mid-execution, and document design options for micro-x-agent-loop-python.

---

## Problem Statement

The current micro-x-agent-loop-python has a **unidirectional interaction model**: the user provides input, the agent processes it (potentially calling tools in a loop), and returns output. The agent cannot pause mid-execution to ask the user a clarifying question, present choices, or request approval.

This matters because:
- Ambiguous instructions lead to wasted tokens on wrong interpretations
- Architectural/design decisions benefit from user input before implementation
- Some tool calls (destructive operations) should require explicit approval
- The agent may discover missing information mid-task that only the user can provide

---

## Survey of Implementations

### 1. Claude Code — `AskUserQuestion` Tool

**The gold standard for structured user questioning.**

Claude Code defines `AskUserQuestion` as a first-class tool with a rich JSON schema:

```json
{
  "questions": [{
    "question": "Which authentication approach should we use?",
    "header": "Auth method",
    "multiSelect": false,
    "options": [
      {"label": "OAuth 2.0 (Recommended)", "description": "Industry standard, supports SSO"},
      {"label": "API Keys", "description": "Simple, stateless, server-to-server"},
      {"label": "JWT Sessions", "description": "Custom implementation, full control"}
    ]
  }]
}
```

**Key design decisions:**

| Aspect | Design |
|--------|--------|
| Questions per call | 1–4 |
| Options per question | 2–4 (structured) |
| Free-text escape | Always available via auto-appended "Other" option |
| Recommended option | First in list, suffixed with "(Recommended)" |
| Multi-select | Supported via `multiSelect: boolean` |
| Answer format | `{"question text": "selected label or free text"}` |

**How the loop handles it:**

The critical insight is that `AskUserQuestion` is a **pseudo-tool** — it never executes code. Instead, Claude Code hijacks the `canUseTool` permission callback:

```
LLM emits tool_use(name="AskUserQuestion", input={questions: [...]})
  → canUseTool callback detects tool name
  → callback presents questions to user, collects answers
  → callback returns PermissionResultAllow(updatedInput={questions, answers})
  → updatedInput becomes the tool_result
  → LLM sees answers in the next turn
```

The loop blocks at the `canUseTool` await point. No special suspend/resume machinery needed — the async callback simply doesn't resolve until the user responds.

**Subagent restriction:** `AskUserQuestion` is explicitly filtered out from subagents. Only the main agent can interrupt the user. This prevents background tasks from blocking on user input.

**Limitations:** 60-second timeout on responses. Known bugs with empty answers being returned without waiting.

---

### 2. Cline / Roo Code / Kilo Code — `ask_followup_question` XML Tool

**XML-based variant of the same pattern.**

```xml
<ask_followup_question>
  <question>Which styling approach would you prefer?</question>
  <follow_up>
    <suggest>Use Bootstrap for rapid development</suggest>
    <suggest>Use Tailwind CSS for utility-first styling</suggest>
  </follow_up>
</ask_followup_question>
```

Tools are defined as XML structures in the system prompt, not JSON function schemas. The runtime parses XML from the model's text output. The user response is wrapped in `<answer>` tags and appended to conversation history.

Cline also has a separate per-action approval flow — every file edit and command renders a diff/preview and waits for "Approve"/"Reject".

---

### 3. LangGraph — `interrupt()` + `Command(resume=...)`

**The most architecturally sophisticated approach, designed for distributed/stateless systems.**

```python
from langgraph.types import interrupt, Command

def approval_node(state):
    answer = interrupt({"question": "Approve this transfer?", "amount": state["amount"]})
    if answer == "approved":
        return execute_transfer(state)
```

`interrupt()` throws a special exception caught by the LangGraph runtime. The runtime serializes the entire graph state to a checkpointer (SQLite, Postgres, etc.) and returns the interrupt payload to the caller. The process can die.

Resumption:
```python
graph.invoke(Command(resume="approved"), config={"configurable": {"thread_id": "t1"}})
```

The `Command(resume=...)` value becomes the return value of `interrupt()`. The node restarts from the beginning (pre-interrupt code runs again — must be idempotent).

**Key differentiator:** True process-independent persistence. All other systems require the process to stay alive during the pause.

**No enforced schema** on interrupt payloads or resume values — any JSON-serializable data works.

---

### 4. OpenAI Agents SDK — `needs_approval` Flag

**Approval-only, not questioning.**

```python
@function_tool(needs_approval=True)
def delete_files(pattern: str): ...
```

When a flagged tool is called, the SDK returns an `interruptions` array. The caller approves or rejects:

```python
result = await Runner.run(agent, "Delete temp files")
state = result.to_state()
for interruption in result.interruptions:
    state.approve(interruption)
result = await Runner.run(agent, state)
```

**Limitation:** Binary approve/reject only. The model cannot formulate questions or present choices. This is a runtime safety gate, not a communication channel.

---

### 5. Mastra — `suspend()` / `resumeData`

**Tool-level suspend/resume with typed schemas.**

```typescript
execute: async ({ context, suspend, resumeData }) => {
  if (context.amount > 1000 && !resumeData) {
    return await suspend({ reason: `Transfer of $${context.amount} requires approval` });
  }
  if (resumeData?.approved) {
    await executeTransfer(context);
  }
}
```

Tools define `suspendSchema` and `resumeSchema` for type safety. State persists to storage.

**Notable UX innovation:** "Conversational auto-resume" — the agent tracks pending suspensions and, when the user replies in natural language, maps the response to the pending tool without requiring programmatic `resume()` calls.

---

### 6. Aider — Hardcoded Confirmation Points

**Simplest approach: `confirm_ask()` calls at fixed points in the coder loop.**

```python
if io.confirm_ask("Apply these edits?", default="y"):
    apply_edits()
```

The runtime (not the model) decides when to ask. Questions are yes/no with "don't ask again" support. No structured choices. No model agency over when to ask.

---

### 7. OpenClaw — No Built-in Mechanism

OpenClaw does not have an `ask_user` tool. Each user message triggers a complete loop invocation. Agent-to-human communication is asynchronous through messaging channels (WhatsApp, Telegram, Slack). There was an open feature request for gateway-level approval middleware that was closed without implementation.

---

### 8. Other Notable Approaches

| System | Approach | Notes |
|--------|----------|-------|
| **Haystack** | `BlockingConfirmationStrategy` + per-tool policies + `HumanInTheLoopTool` | Policies: always ask, never ask, ask once, custom. Also has a tool the model can call. |
| **CrewAI** | `human_input=True` task flag + custom `@tool` for questions | Task-level flag is terminal confirmation, not mid-loop. |
| **HumanLayer** | `@require_approval` + `human_as_tool()` decorators (cross-framework) | Routes approvals over Slack/email. Framework-agnostic. |
| **Continue.dev** | Per-tool policy (automatic/ask/disabled) | Approval only, no model-initiated questions. |
| **AG-UI Protocol** | Event-based protocol standard with ~16 event types including HITL | Protocol spec, not implementation. Positions itself as "agent-to-user" layer alongside MCP (agent-to-tool). |

---

## Architectural Patterns

Six distinct patterns emerge from the survey:

### Pattern 1: Tool-as-Question (Claude Code, Cline, Haystack HumanInTheLoopTool)

The model explicitly calls a tool designed for asking questions. The tool schema defines the question format. The runtime renders the UI, collects the response, returns it as tool_result.

```
Model → tool_use("ask_user", {question, options})
Runtime → present to user, collect answer
Runtime → tool_result({answer})
Model → continues with answer
```

**Pros:** Model has full agency over when to ask and what to ask. Structured schema prevents ambiguous questions. Fits naturally into the tool_use/tool_result protocol.

**Cons:** Model may over-use or under-use the tool. Requires good system prompt guidance. The tool never "executes" in the traditional sense — it's a communication channel disguised as a tool.

### Pattern 2: Approval Gate (OpenAI, Continue, Mastra declarative)

Tools are flagged as requiring approval. The runtime intercepts before execution and presents the call for user review.

**Pros:** Simple to implement. No model behavior change needed.

**Cons:** Binary approve/reject only. Model cannot formulate questions. Limited to "should this run?" decisions.

### Pattern 3: Exception-Based Suspend/Resume (LangGraph)

`interrupt()` throws an exception. Runtime catches it, serializes state, returns to caller. Resume via `Command(resume=value)` on a new invocation.

**Pros:** Process-independent persistence. Production-grade for distributed systems.

**Cons:** Complex. Pre-interrupt code must be idempotent. No standard question schema.

### Pattern 4: Callback-Based Blocking (Claude Agent SDK)

An async callback fires before tool execution. The loop awaits the callback. The callback blocks while collecting user input.

**Pros:** Simple to implement in async systems. No state serialization needed.

**Cons:** Process must stay alive. Long pauses can cause timeouts.

### Pattern 5: Messaging-Channel Loop (OpenClaw, HumanLayer)

Agent sends a message via external channel. User reply triggers a new invocation.

**Pros:** Works for long-running async workflows. No process to keep alive.

**Cons:** No pause within a single run. Context must be reconstructed on each invocation.

### Pattern 6: Hardcoded Confirmation Points (Aider)

Fixed points in the code ask specific questions. No model agency.

**Pros:** Dead simple. Predictable.

**Cons:** Inflexible. Cannot adapt to novel situations. Not a real "ask user" mechanism.

---

## Comparative Matrix

| Feature | Claude Code | Cline | LangGraph | OpenAI | Mastra | Aider |
|---------|------------|-------|-----------|--------|--------|-------|
| Model initiates questions | Yes | Yes | Yes | No | Yes | No |
| Structured choices | 2–4 options | 2–4 suggestions | Unconstrained | Approve/Reject | Via schema | Yes/No |
| Free-text fallback | "Other" option | Free text | Any JSON | No | Via resume data | No |
| Multiple questions per call | 1–4 | 1 | 1 per interrupt | N/A | 1 per suspend | N/A |
| Multi-select | Yes | No | Unconstrained | No | Via schema | No |
| Process survives restart | No | No | Yes | Semi | Yes | No |
| Requires schema | Yes (strict) | Loose XML | No | N/A | Optional | N/A |
| Subagent support | No (blocked) | N/A | Yes | Yes | N/A | N/A |

---

## Design Recommendations for micro-x-agent-loop-python

### Recommended: Pattern 1 (Tool-as-Question) — Claude Code Style

This is the best fit for micro-x-agent-loop-python because:

1. **It uses the existing tool_use/tool_result protocol.** No new message types, no exception handling, no state serialization. The agent loop already handles tool calls — this is just a special-cased one.

2. **The model has agency.** The LLM decides when to ask and what to ask, based on the task context. This is more flexible than hardcoded confirmation points.

3. **Structured schema prevents ambiguity.** The LLM must provide clear options with descriptions, not vague open-ended questions.

4. **It's simple to implement.** The core change is:
   - Define the tool schema and add it to the system prompt
   - In `TurnEngine.execute_tools()`, detect the tool name and route to a user-input handler instead of executing
   - The handler collects input via `asyncio.to_thread(input, ...)` (matching the existing REPL pattern)
   - Return the answer as a normal `tool_result`

### Proposed Schema (Simplified from Claude Code)

```python
ASK_USER_TOOL_SCHEMA = {
    "name": "ask_user",
    "description": (
        "Ask the user a question when you need clarification, "
        "a decision between approaches, or approval for an action. "
        "Use this when the task is ambiguous or when multiple valid "
        "approaches exist. Do NOT use this for rhetorical questions "
        "or when you can make a reasonable default choice."
    ),
    "input_schema": {
        "type": "object",
        "required": ["question"],
        "properties": {
            "question": {
                "type": "string",
                "description": "Clear, specific question ending with '?'"
            },
            "options": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["label", "description"],
                    "properties": {
                        "label": {"type": "string"},
                        "description": {"type": "string"}
                    }
                },
                "minItems": 2,
                "maxItems": 4,
                "description": "Suggested choices. User can always type a custom answer."
            }
        }
    }
}
```

**Simplifications from Claude Code:**
- Single question per call (no batching) — simpler to implement, and the model can call the tool multiple times if needed
- No `header` field — unnecessary for terminal UI
- No `multiSelect` — can be added later if needed
- Renamed to `ask_user` — shorter, matches the project's naming conventions

### Implementation Sketch

```python
# In turn_engine.py — tool execution loop

async def _handle_tool_calls(self, tool_blocks):
    ask_user_blocks = [b for b in tool_blocks if b["name"] == "ask_user"]
    regular_blocks = [b for b in tool_blocks if b["name"] != "ask_user"]

    results = []

    # Handle ask_user FIRST (before running other tools)
    for block in ask_user_blocks:
        answer = await self._ask_user(block["input"])
        results.append({
            "type": "tool_result",
            "tool_use_id": block["id"],
            "content": json.dumps({"answer": answer})
        })

    # Then execute regular tools in parallel as before
    if regular_blocks:
        regular_results = await execute_tools(regular_blocks, ...)
        results.extend(regular_results)

    return results


async def _ask_user(self, input_data: dict) -> str:
    question = input_data["question"]
    options = input_data.get("options", [])

    print(f"\nassistant> Question: {question}")
    if options:
        for i, opt in enumerate(options, 1):
            print(f"  {i}. {opt['label']} — {opt['description']}")
        print(f"  (Enter 1-{len(options)}, or type your own answer)")

    raw = await asyncio.to_thread(input, "you> ")

    # Map number to option label
    if options and raw.strip().isdigit():
        idx = int(raw.strip()) - 1
        if 0 <= idx < len(options):
            return options[idx]["label"]

    return raw.strip()
```

### System Prompt Addition

```
You have access to an `ask_user` tool. Use it when:
- The task is ambiguous and multiple valid interpretations exist
- You need to choose between architectural approaches with different tradeoffs
- You discover missing requirements mid-task that only the user can provide
- A destructive or irreversible action needs explicit approval

Do NOT use it when:
- You can make a reasonable default choice
- The question is rhetorical or the answer is obvious from context
- You're asking for permission to do something the user already requested
```

### Future Extensions

1. **Approval gate (Pattern 2):** Add an `is_mutating` check on tools. Before executing mutating tools, present a confirmation. This is orthogonal to `ask_user` and can coexist.

2. **Rich terminal UI:** Replace `input()` with `prompt_toolkit` for arrow-key selection, syntax highlighting of options, and timeout support.

3. **Subagent restriction:** If/when subagents are added, filter `ask_user` from subagent tool lists.

4. **Conversational auto-resume (Mastra-style):** Instead of blocking the loop, the agent could note what it's waiting for and continue with other work. When the user's next message arrives, map it to the pending question. This is significantly more complex but enables non-blocking workflows.

---

## References

- [Claude Code system prompt — AskUserQuestion](https://github.com/Piebald-AI/claude-code-system-prompts)
- [Claude Agent SDK — Handle approvals and user input](https://platform.claude.com/docs/en/agent-sdk/user-input)
- [LangGraph — Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [OpenAI Agents SDK — Human in the Loop](https://openai.github.io/openai-agents-js/guides/human-in-the-loop/)
- [Mastra — Tool Approval](https://mastra.ai/blog/tool-approval)
- [Cline GitHub](https://github.com/cline/cline)
- [Kilo Code — ask_followup_question](https://kilo.ai/docs/features/tools/ask-followup-question)
- [Haystack — Human in the Loop Agent](https://haystack.deepset.ai/tutorials/47_human_in_the_loop_agent)
- [AG-UI Protocol](https://docs.ag-ui.com/)
- [HumanLayer](https://www.humanlayer.dev/docs/quickstart-python)

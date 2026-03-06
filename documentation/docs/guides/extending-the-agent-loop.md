# Guide: Extending the Agent Loop

How to add new behaviour to the agent loop via the event callback system.

## Architecture

The agent loop has two layers:

| Component | Role | File |
|-----------|------|------|
| **Agent** | Orchestrator — message history, memory, metrics, mode analysis | `agent.py` |
| **TurnEngine** | Single turn — LLM call, tool dispatch, response streaming | `turn_engine.py` |

`TurnEngine` communicates back to `Agent` via the **TurnEvents** protocol defined in `turn_events.py`. This decouples turn execution from session management.

## The TurnEvents Protocol

```python
# turn_events.py (simplified)
class TurnEvents(Protocol):
    def on_api_call_completed(self, usage: UsageResult, call_type: str) -> None: ...
    def on_tool_executed(self, tool_name: str, result_chars: int, ...) -> None: ...
    async def on_maybe_compact(self) -> None: ...
    def on_append_message(self, role: str, content: str | list[dict]) -> str | None: ...
    def on_ensure_checkpoint_for_turn(self, tool_use_blocks: list[dict]) -> None: ...
    def on_maybe_track_mutation(self, tool_name: str, tool: Tool, tool_input: dict) -> None: ...
    def on_tool_started(self, tool_use_id: str, tool_name: str) -> None: ...
    def on_tool_completed(self, tool_use_id: str, tool_name: str, is_error: bool) -> None: ...
    def on_user_message_appended(self, message_id: str | None) -> None: ...
    def on_record_tool_call(self, *, tool_call_id: str, ...) -> None: ...
```

## Adding a New Callback

### 1. Define the callback in TurnEvents

```python
# turn_events.py
class TurnEvents(Protocol):
    # ... existing callbacks ...
    def on_my_new_event(self, data: str) -> None: ...
```

### 2. Implement in Agent

```python
# agent.py
def on_my_new_event(self, data: str) -> None:
    logger.info(f"New event: {data}")
    # Persist, emit metric, update state, etc.
```

### 3. Call from TurnEngine

```python
# turn_engine.py
self._events.on_my_new_event(some_data)
```

## Common Extension Points

### Adding Pre-Turn Logic

Modify `Agent._run_inner()` — this runs before `TurnEngine.run()`:

```python
async def _run_inner(self, user_message: str) -> None:
    # Command handling
    if await self._handle_local_command(user_message):
        return

    # Mode analysis (existing)
    if self._mode_analysis_enabled:
        ...

    # YOUR NEW PRE-TURN LOGIC HERE

    # Turn execution
    await self._turn_engine.run(...)
```

### Adding Post-Tool Logic

Use `on_tool_executed` or `on_tool_completed` in `Agent`:

```python
def on_tool_executed(self, tool_name: str, result_chars: int, ...):
    # Existing metrics logic
    ...
    # Your new logic
    if tool_name == "special_tool":
        self._handle_special_result(...)
```

### Adding a Slash Command

1. Add handler to `commands/command_handler.py`:

```python
async def handle_my_command(self, args: str) -> None:
    print(f"{self._line_prefix}My command: {args}")
```

2. Register in `commands/router.py`:

```python
# In CommandRouter.__init__
self._routes["my_command"] = on_my_command
```

3. Wire in `Agent.__init__`:

```python
self._command_router = CommandRouter(
    ...
    on_my_command=self._command_handler.handle_my_command,
)
```

### Adding a New Compaction Strategy

1. Subclass in `compaction.py`:

```python
class MyCompactionStrategy(CompactionStrategy):
    async def maybe_compact(self, messages: list[dict]) -> list[dict]:
        # Your compaction logic
        return messages
```

2. Register in `bootstrap.py` strategy selection.

## Testing

Use the `FakeStreamProvider` from `tests/fakes.py` for unit testing:

```python
from tests.fakes import FakeStreamProvider, FakeTool
from unittest.mock import patch

fake_provider = FakeStreamProvider()
fake_provider.queue(text="Hello!", stop_reason="end_turn")

with patch("micro_x_agent_loop.agent.create_provider", return_value=fake_provider):
    agent = Agent(AgentConfig(api_key="test", tools=[FakeTool()]))

asyncio.run(agent.run("test message"))
```

## Related

- [Agent Loop Design](../design/DESIGN-agent-loop.md)
- [Tool System Design](../design/DESIGN-tool-system.md)
- [Compaction Design](../design/DESIGN-compaction.md)

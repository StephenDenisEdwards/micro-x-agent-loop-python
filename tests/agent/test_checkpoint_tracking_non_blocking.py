import asyncio
import unittest
from typing import Any

from micro_x_agent_loop.agent import Agent
from micro_x_agent_loop.agent_config import AgentConfig


class _MutatingTool:
    def __init__(self):
        self.execute_calls = 0

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "test tool"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"path": {"type": "string"}}}

    @property
    def is_mutating(self) -> bool:
        return True

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        return [tool_input.get("path", "")]

    async def execute(self, tool_input: dict[str, Any]) -> str:
        self.execute_calls += 1
        return "tool executed"


class _RaisingCheckpointManager:
    enabled = True
    write_tools_only = True

    def maybe_track_tool_input(self, checkpoint_id: str, tool_input: dict) -> list[str]:
        raise ValueError("outside working directory")


class _NoopEvents:
    def emit(self, session_id: str, event_type: str, payload: dict) -> None:
        return


class CheckpointTrackingNonBlockingTests(unittest.TestCase):
    def test_tracking_failure_does_not_fail_tool_execution(self) -> None:
        tool = _MutatingTool()
        agent = Agent(
            AgentConfig(
                api_key="test-key",
                tools=[tool],
                memory_enabled=True,
                session_id="s1",
                checkpoint_manager=_RaisingCheckpointManager(),
                event_emitter=_NoopEvents(),
            )
        )
        agent._current_checkpoint_id = "cp-1"

        result = asyncio.run(
            agent._execute_tools(
                [
                    {
                        "name": "write_file",
                        "id": "tool-1",
                        "input": {"path": "C:/outside.txt", "content": "x"},
                    }
                ]
            )
        )

        self.assertEqual(1, tool.execute_calls)
        self.assertEqual("tool executed", result[0]["content"])
        self.assertNotIn("is_error", result[0])


if __name__ == "__main__":
    unittest.main()

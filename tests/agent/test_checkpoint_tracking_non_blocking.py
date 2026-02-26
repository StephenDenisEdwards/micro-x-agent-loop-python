import asyncio
import unittest

from micro_x_agent_loop.agent import Agent
from micro_x_agent_loop.agent_config import AgentConfig
from tests.fakes import FakeEventEmitter, FakeTool


class _RaisingCheckpointManager:
    enabled = True
    write_tools_only = True

    def maybe_track_tool_input(self, checkpoint_id: str, tool_input: dict) -> list[str]:
        raise ValueError("outside working directory")


class CheckpointTrackingNonBlockingTests(unittest.TestCase):
    def test_tracking_failure_does_not_fail_tool_execution(self) -> None:
        tool = FakeTool(
            name="write_file",
            description="test tool",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            execute_result="tool executed",
            is_mutating=True,
            touched_paths=[""],
        )
        agent = Agent(
            AgentConfig(
                api_key="test-key",
                tools=[tool],
                memory_enabled=True,
                session_id="s1",
                checkpoint_manager=_RaisingCheckpointManager(),
                event_emitter=FakeEventEmitter(),
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

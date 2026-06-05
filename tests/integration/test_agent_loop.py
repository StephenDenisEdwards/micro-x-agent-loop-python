"""End-to-end integration tests for the agent loop.

These tests build a real ``Agent`` with all default subsystems and drive
it through ``agent.run(...)``. The only thing that is faked is the LLM
provider (``FakeStreamProvider``) — everything else (TurnEngine,
pseudo-tool dispatch, AgentChannel, TurnEvents, memory facade, metrics)
is the real implementation. Each test exercises a distinct path through
the loop that no unit-level test covers end-to-end.

Coverage focus per the codebase review (T3-2):

- single-turn text-only response
- multi-turn tool-call → tool result → final text
- multiple tools in one assistant response (results merged in order)
- ``ask_user`` pseudo-tool routed through the channel
- iteration cap behaviour (``on_turn_cap_reached``)
- tool error propagation as ``is_error: true`` tool_result
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from micro_x_agent_loop.agent import Agent
from micro_x_agent_loop.agent_channel import BufferedChannel
from micro_x_agent_loop.agent_config import AgentConfig
from micro_x_agent_loop.constants import DEFAULT_MAX_AGENTIC_ITERATIONS
from micro_x_agent_loop.usage import UsageResult
from tests.fakes import FakeStreamProvider, FakeTool


def _build_agent(
    provider: FakeStreamProvider,
    *,
    tools: list[FakeTool] | None = None,
    channel: BufferedChannel | None = None,
    max_agentic_iterations: int = DEFAULT_MAX_AGENTIC_ITERATIONS,
    autonomous: bool = True,
) -> Agent:
    """Build a real Agent with the LLM provider mocked.

    ``autonomous=True`` is the default so the run path doesn't try to
    prompt the user for mode analysis. ``channel`` defaults to a
    ``BufferedChannel`` so output is captured and ``ask_user`` returns
    the standard timeout sentinel.
    """
    channel = channel or BufferedChannel()
    config = AgentConfig(
        api_key="test-key",
        provider="anthropic",
        model="test-model",
        tools=list(tools or []),
        channel=channel,
        autonomous=autonomous,
        memory_enabled=False,
        metrics_enabled=True,
        max_agentic_iterations=max_agentic_iterations,
    )
    with patch(
        "micro_x_agent_loop.agent_builder.create_provider",
        return_value=provider,
    ):
        return Agent(config)


class SingleTurnTextOnlyTests(unittest.IsolatedAsyncioTestCase):
    """No tools, no iterations — assistant replies with text and stops."""

    async def test_text_only_response_appends_messages_and_returns(self) -> None:
        provider = FakeStreamProvider()
        provider.queue(text="Hello, world.", stop_reason="end_turn")

        channel = BufferedChannel()
        agent = _build_agent(provider, channel=channel)
        await agent.run("hi")

        # The provider was called exactly once for the single turn.
        self.assertEqual(1, len(provider.stream_calls))
        # The channel accumulated the assistant's text (BufferedChannel.text).
        # Channel text is only populated via emit_text_delta, which
        # FakeStreamProvider does not emit, but the assistant message
        # was still appended to the in-memory history.
        history = agent._messages
        self.assertEqual("user", history[0]["role"])
        self.assertEqual("hi", history[0]["content"])
        self.assertEqual("assistant", history[1]["role"])
        # One turn fully completed.
        self.assertEqual(1, agent._turn_number)


class MultiTurnToolCallTests(unittest.IsolatedAsyncioTestCase):
    """user → assistant(tool_use) → user(tool_result) → assistant(text)."""

    async def test_tool_call_then_final_reply(self) -> None:
        tool = FakeTool(name="read_file", execute_result="file contents")
        provider = FakeStreamProvider()
        # Turn 1 (iter 0): assistant calls the tool.
        provider.responses.append(
            (
                {"role": "assistant", "content": [{"type": "text", "text": "Reading."}]},
                [{"name": "read_file", "id": "t1", "input": {"path": "x.py"}}],
                "tool_use",
                UsageResult(input_tokens=10, output_tokens=5, model="m"),
            )
        )
        # Turn 1 (iter 1): assistant produces the final reply.
        provider.queue(text="Done.", stop_reason="end_turn")

        agent = _build_agent(provider, tools=[tool])
        await agent.run("read the file")

        # The tool was executed exactly once.
        self.assertEqual(1, tool.execute_calls)
        # Two API calls in the same turn.
        self.assertEqual(2, len(provider.stream_calls))
        # History layout: user, assistant(tool_use), user(tool_result), assistant(final)
        history = agent._messages
        self.assertEqual("user", history[0]["role"])
        self.assertEqual("assistant", history[1]["role"])
        self.assertEqual("user", history[2]["role"])
        results = history[2]["content"]
        self.assertIsInstance(results, list)
        self.assertEqual(1, len(results))
        self.assertEqual("t1", results[0]["tool_use_id"])
        self.assertEqual("file contents", results[0]["content"])
        # Final assistant reply present.
        self.assertEqual("assistant", history[3]["role"])


class MultipleToolsInOneResponseTests(unittest.IsolatedAsyncioTestCase):
    """Both tools execute; results are merged in original block order."""

    async def test_two_tools_both_execute_results_in_order(self) -> None:
        tool_a = FakeTool(name="tool_a", execute_result="A out")
        tool_b = FakeTool(name="tool_b", execute_result="B out")
        provider = FakeStreamProvider()
        provider.responses.append(
            (
                {"role": "assistant", "content": [{"type": "text", "text": "Running."}]},
                [
                    {"name": "tool_a", "id": "ta", "input": {}},
                    {"name": "tool_b", "id": "tb", "input": {}},
                ],
                "tool_use",
                UsageResult(input_tokens=10, output_tokens=5, model="m"),
            )
        )
        provider.queue(text="All done.", stop_reason="end_turn")

        agent = _build_agent(provider, tools=[tool_a, tool_b])
        await agent.run("run both")

        self.assertEqual(1, tool_a.execute_calls)
        self.assertEqual(1, tool_b.execute_calls)
        # Tool results appended to history with correct ordering.
        results = agent._messages[2]["content"]
        self.assertEqual(2, len(results))
        self.assertEqual("ta", results[0]["tool_use_id"])
        self.assertEqual("tb", results[1]["tool_use_id"])


class AskUserPseudoToolTests(unittest.IsolatedAsyncioTestCase):
    """ask_user calls flow through the channel, never reach tool_map."""

    async def test_ask_user_response_routed_through_channel(self) -> None:
        provider = FakeStreamProvider()
        # Turn 1 (iter 0): assistant calls ask_user.
        provider.responses.append(
            (
                {"role": "assistant", "content": [{"type": "text", "text": "Asking."}]},
                [{"name": "ask_user", "id": "au1", "input": {"question": "Which file?"}}],
                "tool_use",
                UsageResult(input_tokens=10, output_tokens=5, model="m"),
            )
        )
        provider.queue(text="OK, reading.", stop_reason="end_turn")

        # BufferedChannel.ask_user returns a hard-coded timeout sentinel,
        # which gives us a deterministic value to assert on.
        channel = BufferedChannel()
        agent = _build_agent(provider, channel=channel)
        await agent.run("help me")

        # The tool_map was never touched (no tools registered).
        # The ask_user result lands as a tool_result with the channel's answer.
        results = agent._messages[2]["content"]
        self.assertEqual(1, len(results))
        self.assertEqual("au1", results[0]["tool_use_id"])
        parsed = json.loads(results[0]["content"])
        self.assertIn("answer", parsed)
        self.assertIn("No response from human", parsed["answer"])


class IterationCapTests(unittest.IsolatedAsyncioTestCase):
    """When the assistant keeps calling tools, the agentic-iteration cap fires."""

    async def test_cap_reached_triggers_signal(self) -> None:
        tool = FakeTool(name="loop_tool", execute_result="more")
        provider = FakeStreamProvider()
        # The assistant calls the tool on every iteration so the loop only
        # ends when the cap is reached. Queue more responses than the cap
        # to be safe.
        cap = 3
        for _ in range(cap + 2):
            provider.responses.append(
                (
                    {"role": "assistant", "content": [{"type": "text", "text": "again"}]},
                    [{"name": "loop_tool", "id": f"t{_}", "input": {}}],
                    "tool_use",
                    UsageResult(input_tokens=10, output_tokens=5, model="m"),
                )
            )

        agent = _build_agent(provider, tools=[tool], max_agentic_iterations=cap)
        await agent.run("loop forever")

        # The cap signal must be set on the accumulator.
        self.assertTrue(agent._session_accumulator.turn_cap_reached)


class ToolErrorPropagationTests(unittest.IsolatedAsyncioTestCase):
    """A tool that raises produces an ``is_error: True`` tool_result."""

    async def test_tool_exception_surfaces_as_is_error_result(self) -> None:
        tool = FakeTool(
            name="bad_tool",
            execute_side_effect=RuntimeError("boom"),
        )
        provider = FakeStreamProvider()
        provider.responses.append(
            (
                {"role": "assistant", "content": [{"type": "text", "text": "Try."}]},
                [{"name": "bad_tool", "id": "tb", "input": {}}],
                "tool_use",
                UsageResult(input_tokens=10, output_tokens=5, model="m"),
            )
        )
        provider.queue(text="Recovered.", stop_reason="end_turn")

        agent = _build_agent(provider, tools=[tool])
        await agent.run("invoke the bad tool")

        # Tool was attempted.
        self.assertEqual(1, tool.execute_calls)
        # The tool_result block carries is_error: True
        results = agent._messages[2]["content"]
        self.assertEqual(1, len(results))
        self.assertTrue(results[0].get("is_error"))
        # The final assistant message is still present.
        self.assertEqual("assistant", agent._messages[3]["role"])


if __name__ == "__main__":
    unittest.main()

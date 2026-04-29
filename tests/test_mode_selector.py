import asyncio
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, patch

from micro_x_agent_loop.agent import Agent
from micro_x_agent_loop.agent_config import AgentConfig
from micro_x_agent_loop.mode_selector import (
    ModeAnalysis,
    RecommendedMode,
    Stage2Result,
    analyze_prompt,
    build_stage2_prompt,
    format_analysis,
    format_stage2_result,
    parse_stage2_response,
)
from micro_x_agent_loop.usage import UsageResult
from tests.fakes import FakeStreamProvider, FakeTool


class SignalDetectionTests(unittest.TestCase):
    """Individual signal detection."""

    def _signal_names(self, analysis: ModeAnalysis) -> set[str]:
        return {s.name for s in analysis.signals}

    def test_batch_processing_each(self) -> None:
        analysis = analyze_prompt("Score each job against my criteria")
        self.assertIn("Batch processing", self._signal_names(analysis))

    def test_batch_processing_all(self) -> None:
        analysis = analyze_prompt("search Gmail for all emails received today")
        self.assertIn("Batch processing", self._signal_names(analysis))

    def test_batch_processing_every(self) -> None:
        analysis = analyze_prompt("check every listing for duplicates")
        self.assertIn("Batch processing", self._signal_names(analysis))

    def test_scoring_score(self) -> None:
        analysis = analyze_prompt("Score each job 1-10")
        self.assertIn("Scoring/ranking", self._signal_names(analysis))

    def test_scoring_rank(self) -> None:
        analysis = analyze_prompt("Rank the candidates by experience")
        self.assertIn("Scoring/ranking", self._signal_names(analysis))

    def test_scoring_evaluate(self) -> None:
        analysis = analyze_prompt("Evaluate each option carefully")
        self.assertIn("Scoring/ranking", self._signal_names(analysis))

    def test_scoring_compare(self) -> None:
        analysis = analyze_prompt("Compare the two proposals")
        self.assertIn("Scoring/ranking", self._signal_names(analysis))

    def test_stats_total(self) -> None:
        analysis = analyze_prompt("Show the total number of jobs found")
        self.assertIn("Statistics/aggregation", self._signal_names(analysis))

    def test_stats_average(self) -> None:
        analysis = analyze_prompt("Calculate the average score")
        self.assertIn("Statistics/aggregation", self._signal_names(analysis))

    def test_stats_distribution(self) -> None:
        analysis = analyze_prompt("Show the distribution of scores")
        self.assertIn("Statistics/aggregation", self._signal_names(analysis))

    def test_stats_summary_statistics(self) -> None:
        analysis = analyze_prompt("Include Summary Statistics at the end")
        self.assertIn("Statistics/aggregation", self._signal_names(analysis))

    def test_mandatory_fields_must_include(self) -> None:
        analysis = analyze_prompt("Each entry must include a link")
        self.assertIn("Mandatory fields", self._signal_names(analysis))

    def test_mandatory_fields_always_include(self) -> None:
        analysis = analyze_prompt("Always include the source URL")
        self.assertIn("Mandatory fields", self._signal_names(analysis))

    def test_mandatory_fields_required(self) -> None:
        analysis = analyze_prompt("The score field is required")
        self.assertIn("Mandatory fields", self._signal_names(analysis))

    def test_mandatory_fields_ensure(self) -> None:
        analysis = analyze_prompt("Ensure every job has a salary listed")
        self.assertIn("Mandatory fields", self._signal_names(analysis))

    def test_structured_output_markdown(self) -> None:
        analysis = analyze_prompt("Create a markdown file with the results")
        self.assertIn("Structured output", self._signal_names(analysis))

    def test_structured_output_json(self) -> None:
        analysis = analyze_prompt("Output the results as json")
        self.assertIn("Structured output", self._signal_names(analysis))

    def test_structured_output_csv(self) -> None:
        analysis = analyze_prompt("Export the data to csv")
        self.assertIn("Structured output", self._signal_names(analysis))

    def test_structured_output_template(self) -> None:
        analysis = analyze_prompt("Use the standard template for the report")
        self.assertIn("Structured output", self._signal_names(analysis))

    def test_multiple_sources_gmail_linkedin(self) -> None:
        analysis = analyze_prompt("Search Gmail and LinkedIn for jobs")
        self.assertIn("Multiple data sources", self._signal_names(analysis))

    def test_multiple_sources_email_calendar(self) -> None:
        analysis = analyze_prompt("Check my email and calendar for conflicts")
        self.assertIn("Multiple data sources", self._signal_names(analysis))

    def test_single_source_no_signal(self) -> None:
        analysis = analyze_prompt("Search Gmail for emails")
        self.assertNotIn("Multiple data sources", self._signal_names(analysis))

    def test_reproducibility_daily(self) -> None:
        analysis = analyze_prompt("Run this daily")
        self.assertIn("Reproducibility", self._signal_names(analysis))

    def test_reproducibility_every_morning(self) -> None:
        analysis = analyze_prompt("Do this every morning at 9am")
        self.assertIn("Reproducibility", self._signal_names(analysis))

    def test_reproducibility_recurring(self) -> None:
        analysis = analyze_prompt("This is a recurring task")
        self.assertIn("Reproducibility", self._signal_names(analysis))

    def test_batch_numeric_quantity(self) -> None:
        analysis = analyze_prompt("list the last 100 emails")
        self.assertIn("Batch processing", self._signal_names(analysis))

    def test_batch_numeric_top_n(self) -> None:
        analysis = analyze_prompt("get the top 50 results")
        self.assertIn("Batch processing", self._signal_names(analysis))

    def test_batch_numeric_single_item_no_signal(self) -> None:
        analysis = analyze_prompt("Send 1 email to John")
        self.assertNotIn("Batch processing", self._signal_names(analysis))

    def test_stats_summarize(self) -> None:
        analysis = analyze_prompt("summarize the content")
        self.assertIn("Statistics/aggregation", self._signal_names(analysis))

    def test_stats_summaries(self) -> None:
        analysis = analyze_prompt("create summaries of each item")
        self.assertIn("Statistics/aggregation", self._signal_names(analysis))

    # Negative cases
    def test_no_signals_simple_question(self) -> None:
        analysis = analyze_prompt("What's the weather in London?")
        self.assertEqual(0, len(analysis.signals))

    def test_no_signals_greeting(self) -> None:
        analysis = analyze_prompt("Hello, how are you?")
        self.assertEqual(0, len(analysis.signals))

    def test_batch_not_triggered_by_standalone_each(self) -> None:
        # "each" without action verb or collection noun context
        analysis = analyze_prompt("Tell me about each of the planets")
        # This may or may not trigger — the pattern checks for
        # action verb + each OR each + collection noun.
        # "about each" doesn't match either pattern, so no batch signal.
        self.assertNotIn("Batch processing", self._signal_names(analysis))


class DecisionLogicTests(unittest.TestCase):
    """Decision logic: strong/moderate/supportive counts → mode."""

    def test_two_strong_signals_compiled(self) -> None:
        analysis = analyze_prompt("Score each job and calculate the total count")
        self.assertEqual(RecommendedMode.COMPILED, analysis.recommended_mode)
        self.assertGreaterEqual(analysis.strong_count, 2)

    def test_three_strong_signals_compiled(self) -> None:
        analysis = analyze_prompt("Search all emails, score each one, and show the total distribution")
        self.assertEqual(RecommendedMode.COMPILED, analysis.recommended_mode)
        self.assertGreaterEqual(analysis.strong_count, 2)

    def test_zero_signals_prompt(self) -> None:
        analysis = analyze_prompt("What's the weather in London?")
        self.assertEqual(RecommendedMode.PROMPT, analysis.recommended_mode)
        self.assertEqual(0, len(analysis.signals))

    def test_single_strong_ambiguous(self) -> None:
        analysis = analyze_prompt("Score this document for readability")
        self.assertEqual(1, analysis.strong_count)
        self.assertEqual(RecommendedMode.AMBIGUOUS, analysis.recommended_mode)

    def test_moderate_only_ambiguous(self) -> None:
        analysis = analyze_prompt("Output the result as json, ensure it is valid")
        self.assertEqual(0, analysis.strong_count)
        self.assertGreater(len(analysis.signals), 0)
        self.assertEqual(RecommendedMode.AMBIGUOUS, analysis.recommended_mode)

    def test_supportive_only_ambiguous(self) -> None:
        analysis = analyze_prompt("Do this daily please")
        self.assertEqual(0, analysis.strong_count)
        self.assertGreater(len(analysis.signals), 0)
        self.assertEqual(RecommendedMode.AMBIGUOUS, analysis.recommended_mode)


class FormatAnalysisTests(unittest.TestCase):
    """Output formatting."""

    def test_prompt_single_line(self) -> None:
        analysis = analyze_prompt("What time is it?")
        output = format_analysis(analysis)
        self.assertEqual(
            "[Mode Analysis] Recommendation: PROMPT (no compiled-mode signals detected)",
            output,
        )
        self.assertNotIn("\n", output)

    def test_compiled_lists_signals(self) -> None:
        analysis = analyze_prompt("Score each job against criteria and show the total count")
        output = format_analysis(analysis)
        self.assertIn("[Mode Analysis] Recommendation: COMPILED", output)
        self.assertIn("strong", output)
        self.assertIn("Signals:", output)

    def test_ambiguous_lists_signals(self) -> None:
        analysis = analyze_prompt("Score this document")
        output = format_analysis(analysis)
        self.assertIn("[Mode Analysis] Recommendation: AMBIGUOUS", output)
        self.assertIn("Scoring/ranking", output)

    def test_compiled_shows_signal_count_line(self) -> None:
        analysis = analyze_prompt("Score each job and calculate the average across all results")
        output = format_analysis(analysis)
        # Should have a summary line like "Signals: N strong, N moderate, N supportive"
        self.assertRegex(output, r"Signals: \d+ strong, \d+ moderate, \d+ supportive")


class FullPromptIntegrationTests(unittest.TestCase):
    """End-to-end tests with realistic prompts."""

    def test_job_search_prompt_compiled(self) -> None:
        prompt = (
            "Search my Gmail for all JobServe emails received in the last 24 hours. "
            "Read the full content of each email. Then search LinkedIn for similar UK "
            "contract roles. Score each job against my search criteria (1-10). "
            "Exclude roles scoring below 5/10. Create a markdown file. "
            "Include Summary Statistics: Total Jobs Found, Average Score."
        )
        analysis = analyze_prompt(prompt)
        self.assertEqual(RecommendedMode.COMPILED, analysis.recommended_mode)
        self.assertGreaterEqual(analysis.strong_count, 2)

    def test_weather_question_prompt(self) -> None:
        analysis = analyze_prompt("What's the weather in London?")
        self.assertEqual(RecommendedMode.PROMPT, analysis.recommended_mode)

    def test_simple_restaurant_prompt_or_ambiguous(self) -> None:
        analysis = analyze_prompt("Find me 3 good restaurants near the office")
        self.assertIn(
            analysis.recommended_mode,
            {RecommendedMode.PROMPT, RecommendedMode.AMBIGUOUS},
        )

    def test_code_help_prompt(self) -> None:
        analysis = analyze_prompt("How do I reverse a string in Python?")
        self.assertEqual(RecommendedMode.PROMPT, analysis.recommended_mode)

    def test_multi_source_with_scoring_compiled(self) -> None:
        prompt = (
            "Check my Gmail and Slack for any mentions of the project deadline, "
            "then score each message by urgency and show a count of high-priority items"
        )
        analysis = analyze_prompt(prompt)
        self.assertEqual(RecommendedMode.COMPILED, analysis.recommended_mode)


class PromptCommandIntegrationTests(unittest.TestCase):
    """Tests for /prompt command flow — file contents analyzed as user message."""

    def test_file_contents_as_user_message_compiled(self) -> None:
        # Simulates what /prompt does: file contents become the user message
        file_contents = (
            "Search my Gmail for all JobServe emails. Score each job 1-10. Show Summary Statistics with total count."
        )
        analysis = analyze_prompt(file_contents)
        self.assertEqual(RecommendedMode.COMPILED, analysis.recommended_mode)

    def test_bare_meta_instruction_prompt(self) -> None:
        # Without /prompt, a file reference has no signals — known limitation
        analysis = analyze_prompt("run my job-search-prompt.txt prompt")
        self.assertEqual(RecommendedMode.PROMPT, analysis.recommended_mode)


class Stage2PromptTests(unittest.TestCase):
    """Stage 2 prompt construction."""

    def _make_ambiguous_analysis(self, text: str) -> ModeAnalysis:
        analysis = analyze_prompt(text)
        self.assertEqual(RecommendedMode.AMBIGUOUS, analysis.recommended_mode)
        return analysis

    def test_build_prompt_includes_user_message(self) -> None:
        analysis = self._make_ambiguous_analysis("Score this document for readability")
        prompt = build_stage2_prompt("Score this document for readability", analysis)
        self.assertIn("Score this document for readability", prompt)

    def test_build_prompt_includes_stage1_signals(self) -> None:
        analysis = self._make_ambiguous_analysis("Score this document for readability")
        prompt = build_stage2_prompt("Score this document for readability", analysis)
        self.assertIn("Scoring/ranking", prompt)

    def test_build_prompt_includes_classification_guidance(self) -> None:
        analysis = self._make_ambiguous_analysis("Score this document for readability")
        prompt = build_stage2_prompt("Score this document for readability", analysis)
        self.assertIn("PROMPT", prompt)
        self.assertIn("COMPILED", prompt)


class Stage2ResponseParsingTests(unittest.TestCase):
    """Stage 2 response parsing."""

    def test_parse_compiled_response(self) -> None:
        result = parse_stage2_response("COMPILED\nThis is a batch task with many items.")
        self.assertEqual(RecommendedMode.COMPILED, result.recommended_mode)

    def test_parse_prompt_response(self) -> None:
        result = parse_stage2_response("PROMPT\nSingle item, no batch structure.")
        self.assertEqual(RecommendedMode.PROMPT, result.recommended_mode)

    def test_parse_extracts_reasoning(self) -> None:
        result = parse_stage2_response("COMPILED\n50 emails with per-item summarisation is a batch task.")
        self.assertEqual("50 emails with per-item summarisation is a batch task.", result.reasoning)

    def test_parse_defaults_to_compiled(self) -> None:
        result = parse_stage2_response("I'm not sure what to recommend here.")
        self.assertEqual(RecommendedMode.COMPILED, result.recommended_mode)

    def test_parse_case_insensitive(self) -> None:
        for text in ["compiled\nreason", "Compiled\nreason", "COMPILED\nreason"]:
            result = parse_stage2_response(text)
            self.assertEqual(RecommendedMode.COMPILED, result.recommended_mode, f"Failed for: {text}")

        for text in ["prompt\nreason", "Prompt\nreason", "PROMPT\nreason"]:
            result = parse_stage2_response(text)
            self.assertEqual(RecommendedMode.PROMPT, result.recommended_mode, f"Failed for: {text}")


class Stage2FormatTests(unittest.TestCase):
    """Stage 2 output formatting."""

    def test_format_shows_override(self) -> None:
        result = Stage2Result(recommended_mode=RecommendedMode.COMPILED, reasoning="Batch task.")
        output = format_stage2_result(result)
        self.assertIn("Stage 2", output)
        self.assertIn("COMPILED", output)

    def test_format_shows_reasoning(self) -> None:
        result = Stage2Result(recommended_mode=RecommendedMode.PROMPT, reasoning="Single item task.")
        output = format_stage2_result(result)
        self.assertIn("Single item task.", output)
        self.assertIn("Reasoning", output)


class Stage2AgentIntegrationTests(unittest.TestCase):
    """End-to-end: Agent._run_inner triggers (or skips) Stage 2 and prompts the user."""

    def _make_agent(self, *, stage2_response: str = "COMPILED\nBatch task.", stage2_enabled: bool = True) -> Agent:
        """Create an Agent with a fake provider that returns a canned Stage 2 response."""
        fake_provider = FakeStreamProvider()
        # Queue one response for the main turn (after mode analysis)
        fake_provider.queue(text="Hello!", stop_reason="end_turn")

        # FakeStreamProvider doesn't have create_message — add it
        async def fake_create_message(model, max_tokens, temperature, messages):
            return stage2_response, UsageResult(
                input_tokens=300,
                output_tokens=30,
                model=model,
            )

        fake_provider.create_message = fake_create_message

        with patch("micro_x_agent_loop.agent_builder.create_provider", return_value=fake_provider):
            return Agent(
                AgentConfig(
                    api_key="test",
                    tools=[FakeTool()],
                    mode_analysis_enabled=True,
                    stage2_classification_enabled=stage2_enabled,
                    stage2_provider="anthropic",
                    stage2_model="test-model",
                )
            )

    def test_prompt_mode_no_user_prompt(self) -> None:
        """'What's the weather in London?' → PROMPT, no interactive prompt shown."""
        agent = self._make_agent()
        buf = io.StringIO()
        with redirect_stdout(buf):
            asyncio.run(agent.run("What's the weather in London?"))
        out = buf.getvalue()
        self.assertIn("PROMPT", out)
        self.assertNotIn("Which execution mode", out)

    def test_compiled_prompts_user(self) -> None:
        """Full job-search prompt → COMPILED signals → user is prompted to choose."""
        prompt = (
            "Search my Gmail for all JobServe emails received in the last 24 hours. "
            "Read the full content of each email. Then search LinkedIn for similar UK "
            "contract roles. Score each job against my search criteria (1-10). "
            "Exclude roles scoring below 5/10. Create a markdown file. "
            "Include Summary Statistics: Total Jobs Found, Average Score."
        )
        agent = self._make_agent()
        mock_choice = AsyncMock(return_value=RecommendedMode.COMPILED)
        with patch.object(agent, "_prompt_mode_choice", mock_choice):
            buf = io.StringIO()
            with redirect_stdout(buf):
                asyncio.run(agent.run(prompt))
        out = buf.getvalue()
        self.assertIn("Proceeding in COMPILED mode", out)
        mock_choice.assert_called_once()

    def test_compiled_user_overrides_to_prompt(self) -> None:
        """User can override a COMPILED recommendation to PROMPT mode."""
        prompt = "Score each job and calculate the total count across all listings"
        agent = self._make_agent()
        mock_choice = AsyncMock(return_value=RecommendedMode.PROMPT)
        with patch.object(agent, "_prompt_mode_choice", mock_choice):
            buf = io.StringIO()
            with redirect_stdout(buf):
                asyncio.run(agent.run(prompt))
        out = buf.getvalue()
        self.assertIn("Proceeding in PROMPT mode", out)

    def test_ambiguous_prompts_user_with_stage2(self) -> None:
        """AMBIGUOUS → Stage 2 runs, then user is prompted with the recommendation."""
        agent = self._make_agent(stage2_response="COMPILED\nBatch task with 50 items.")
        mock_choice = AsyncMock(return_value=RecommendedMode.COMPILED)
        with patch.object(agent, "_prompt_mode_choice", mock_choice):
            buf = io.StringIO()
            with redirect_stdout(buf):
                asyncio.run(
                    agent.run(
                        "List the last 50 emails from JobServe with the subject "
                        "and then a summary of the content for each."
                    )
                )
        out = buf.getvalue()
        self.assertIn("Proceeding in COMPILED mode", out)
        # Stage2Result should have been passed to the prompt
        args = mock_choice.call_args
        stage2_arg = args[0][1]  # second positional arg
        self.assertIsNotNone(stage2_arg)
        self.assertEqual(RecommendedMode.COMPILED, stage2_arg.recommended_mode)

    def test_ambiguous_stage2_prompt_recommendation(self) -> None:
        """AMBIGUOUS → Stage 2 says PROMPT → user still gets prompted."""
        agent = self._make_agent(stage2_response="PROMPT\nSingle item, no batch.")
        mock_choice = AsyncMock(return_value=RecommendedMode.PROMPT)
        with patch.object(agent, "_prompt_mode_choice", mock_choice):
            buf = io.StringIO()
            with redirect_stdout(buf):
                asyncio.run(agent.run("Score this document for readability"))
        out = buf.getvalue()
        self.assertIn("Proceeding in PROMPT mode", out)
        args = mock_choice.call_args
        stage2_arg = args[0][1]
        self.assertIsNotNone(stage2_arg)
        self.assertEqual(RecommendedMode.PROMPT, stage2_arg.recommended_mode)

    def test_stage2_disabled_still_prompts_user(self) -> None:
        """With Stage 2 disabled, ambiguous prompts still ask the user."""
        fake_provider = FakeStreamProvider()
        fake_provider.queue(text="Hello!", stop_reason="end_turn")
        with patch("micro_x_agent_loop.agent_builder.create_provider", return_value=fake_provider):
            agent = Agent(
                AgentConfig(
                    api_key="test",
                    tools=[FakeTool()],
                    mode_analysis_enabled=True,
                    stage2_classification_enabled=False,
                )
            )
        mock_choice = AsyncMock(return_value=RecommendedMode.COMPILED)
        with patch.object(agent, "_prompt_mode_choice", mock_choice):
            buf = io.StringIO()
            with redirect_stdout(buf):
                asyncio.run(agent.run("Score this document for readability"))
        out = buf.getvalue()
        self.assertIn("Proceeding in COMPILED mode", out)
        # No Stage 2 result should be passed
        args = mock_choice.call_args
        stage2_arg = args[0][1]
        self.assertIsNone(stage2_arg)

    def test_stage2_failure_still_prompts_user(self) -> None:
        """If Stage 2 LLM call fails, the user is still prompted and turn proceeds."""
        fake_provider = FakeStreamProvider()
        fake_provider.queue(text="Hello!", stop_reason="end_turn")

        async def failing_create_message(model, max_tokens, temperature, messages):
            raise RuntimeError("API unavailable")

        fake_provider.create_message = failing_create_message

        with patch("micro_x_agent_loop.agent_builder.create_provider", return_value=fake_provider):
            agent = Agent(
                AgentConfig(
                    api_key="test",
                    tools=[FakeTool()],
                    mode_analysis_enabled=True,
                    stage2_classification_enabled=True,
                    stage2_provider="anthropic",
                    stage2_model="test-model",
                )
            )
        mock_choice = AsyncMock(return_value=RecommendedMode.COMPILED)
        with patch.object(agent, "_prompt_mode_choice", mock_choice):
            buf = io.StringIO()
            with redirect_stdout(buf):
                asyncio.run(agent.run("Score this document for readability"))
        out = buf.getvalue()
        self.assertIn("Proceeding in COMPILED mode", out)
        # Stage 2 failed, so None should be passed
        args = mock_choice.call_args
        stage2_arg = args[0][1]
        self.assertIsNone(stage2_arg)
        # Turn should still proceed
        self.assertEqual(1, agent._turn_number)


if __name__ == "__main__":
    unittest.main()

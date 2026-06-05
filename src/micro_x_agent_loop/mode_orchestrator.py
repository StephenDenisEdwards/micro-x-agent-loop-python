"""Mode analysis orchestrator — encapsulates the PROMPT/COMPILED decision flow.

Extracted from ``Agent`` (was ~135 LOC inline + two private methods). Owns
the three-stage pipeline:

1. ``analyze_prompt`` (Stage 1, deterministic rules + keyword signals).
2. Optional Stage 2 LLM classification when Stage 1 returns AMBIGUOUS.
3. User confirmation via channel modal or terminal questionary.

Returns the ``mode.analyzed`` event payload so the caller can emit it
once the turn actually starts (or ``None`` if analysis is disabled).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

from loguru import logger

from micro_x_agent_loop.mode_selector import (
    ModeAnalysis,
    RecommendedMode,
    Stage2Result,
    analyze_prompt,
    build_stage2_prompt,
    format_analysis,
    parse_stage2_response,
)
from micro_x_agent_loop.usage import UsageResult

if TYPE_CHECKING:
    from micro_x_agent_loop.agent_channel import AgentChannel
    from micro_x_agent_loop.provider import LLMCompactor


class ModeOrchestrator:
    """Runs prompt-mode analysis and surfaces a single ``mode.analyzed`` event.

    Dependencies are injected by the constructor so the orchestrator can
    be reused from Agent (the normal driver) or by tests in isolation.
    """

    def __init__(
        self,
        *,
        enabled: bool,
        autonomous: bool,
        stage2_enabled: bool,
        stage2_provider: LLMCompactor | None,
        stage2_model: str,
        channel: AgentChannel | None,
        system_print: Callable[[str], None],
        on_api_call_completed: Callable[[UsageResult, str], None],
    ) -> None:
        self._enabled = enabled
        self._autonomous = autonomous
        self._stage2_enabled = stage2_enabled
        self._stage2_provider = stage2_provider
        self._stage2_model = stage2_model
        self._channel = channel
        self._system_print = system_print
        self._on_api_call_completed = on_api_call_completed

    async def analyze(self, user_message: str, *, session_id: str) -> dict | None:
        """Run mode analysis. Returns the ``mode.analyzed`` event payload,
        or ``None`` if mode analysis is disabled or the run is autonomous."""
        if not self._enabled or self._autonomous:
            return None

        analysis = analyze_prompt(user_message)
        stage2: Stage2Result | None = None

        if analysis.recommended_mode == RecommendedMode.AMBIGUOUS and self._stage2_enabled:
            try:
                stage2 = await self.classify_ambiguous(user_message, analysis)
            except Exception as ex:
                logger.warning(f"Stage 2 classification failed: {ex}")

        user_choice: str | None = None
        if analysis.signals:
            chosen_mode = await self.prompt_mode_choice(analysis, stage2)
            user_choice = chosen_mode.value
            self._system_print(f"[Mode] Proceeding in {chosen_mode.value} mode")
        else:
            self._system_print(format_analysis(analysis))

        return {
            "session_id": session_id,
            "signals": [
                {"name": s.name, "strength": s.strength.value, "matched_text": s.matched_text}
                for s in analysis.signals
            ],
            "stage1_recommendation": analysis.recommended_mode.value,
            "stage2_recommendation": stage2.recommended_mode.value if stage2 is not None else None,
            "stage2_reasoning": stage2.reasoning if stage2 is not None else "",
            "user_choice": user_choice,
        }

    async def classify_ambiguous(self, user_message: str, stage1: ModeAnalysis) -> Stage2Result:
        """Call the LLM to classify an ambiguous prompt as PROMPT or COMPILED."""
        prompt = build_stage2_prompt(user_message, stage1)
        assert self._stage2_provider is not None
        response_text, usage = await self._stage2_provider.create_message(
            self._stage2_model, 300, 0.0, [{"role": "user", "content": prompt}]
        )
        self._on_api_call_completed(usage, "stage2_classification")
        return parse_stage2_response(response_text)

    async def prompt_mode_choice(
        self,
        analysis: ModeAnalysis,
        stage2: Stage2Result | None,
    ) -> RecommendedMode:
        """Prompt the user to choose between PROMPT and COMPILED execution mode."""
        # Determine the recommendation to present
        if stage2:
            recommended = stage2.recommended_mode
        else:
            recommended = analysis.recommended_mode
        # AMBIGUOUS with no stage2 override defaults to COMPILED recommendation
        if recommended == RecommendedMode.AMBIGUOUS:
            recommended = RecommendedMode.COMPILED

        # Build signal descriptions for display
        signal_texts = [f'{s.name} ({s.strength.value}): "{s.matched_text}"' for s in analysis.signals]
        reasoning = stage2.reasoning if stage2 and stage2.reasoning else ""
        recommended_str = recommended.value

        # Route through channel if it supports mode choice (e.g. TUI modal)
        if self._channel is not None and hasattr(self._channel, "prompt_mode_choice"):
            selected = await self._channel.prompt_mode_choice(
                signal_texts,
                recommended_str,
                reasoning,
            )
            if selected == "COMPILED":
                return RecommendedMode.COMPILED
            if selected == "PROMPT":
                return RecommendedMode.PROMPT
            return recommended

        # Fallback: interactive terminal prompt via questionary
        self._system_print(
            "[Mode Analysis] Your prompt contains signals that suggest "
            "compiled (batch) mode may be more appropriate:"
        )
        for text in signal_texts:
            self._system_print(f"  * {text}")
        if reasoning:
            self._system_print(f"  LLM assessment: {reasoning}")
        self._system_print(
            "  PROMPT mode: conversational, single-turn responses\n"
            "  COMPILED mode: structured batch execution"
        )

        import questionary
        from questionary import Choice, Style

        compiled_label = "COMPILED"
        prompt_label = "PROMPT"
        if recommended == RecommendedMode.COMPILED:
            compiled_label += " (recommended)"
        else:
            prompt_label += " (recommended)"

        choices = [
            Choice(
                title=f"{compiled_label} — structured batch execution",
                value="COMPILED",
            ),
            Choice(
                title=f"{prompt_label} — conversational response",
                value="PROMPT",
            ),
        ]

        style = Style(
            [
                ("qmark", "fg:cyan bold"),
                ("question", "bold"),
                ("pointer", "fg:cyan bold"),
                ("highlighted", "fg:cyan bold"),
                ("selected", "fg:cyan"),
            ]
        )

        def _do_select() -> str | None:
            result: str | None = questionary.select(
                "Which execution mode should be used?",
                choices=choices,
                style=style,
            ).ask()
            return result

        try:
            selected = await asyncio.to_thread(_do_select)
        except Exception:
            self._system_print(
                f"[Mode Analysis] Non-interactive terminal, using recommendation: {recommended.value}"
            )
            return recommended

        if selected == "COMPILED":
            return RecommendedMode.COMPILED
        if selected == "PROMPT":
            return RecommendedMode.PROMPT
        # User cancelled (Ctrl-C) — use recommendation
        return recommended

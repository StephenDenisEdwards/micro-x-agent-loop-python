"""Routing strategy — decides which provider/model handles each API call.

Extracted from ``TurnEngine.run()`` to give routing its own single
responsibility.  Handles pin-continuation, semantic routing, legacy
per-turn routing, confidence gating, and per-policy overrides (tool
narrowing, compact system prompt).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from micro_x_agent_loop.provider_pool import ProviderPool, RoutingTarget
from micro_x_agent_loop.semantic_classifier import TaskClassification
from micro_x_agent_loop.turn_classifier import TurnClassification


@dataclass
class RoutingDecision:
    """Result of a single routing decision."""

    effective_model: str
    effective_provider: Any  # ProviderPool | original provider | None
    routing_target: RoutingTarget | None
    task_classification: TaskClassification | None
    turn_classification: TurnClassification | None
    call_type: str
    system_prompt_override: str | None = None
    narrowed_tools: list[dict] | None = None
    new_pinned_target: RoutingTarget | None = None


class RoutingStrategy:
    """Encapsulates all model-routing logic for a turn engine."""

    def __init__(
        self,
        *,
        default_model: str,
        provider_pool: ProviderPool | None = None,
        semantic_classifier: Any | None = None,
        turn_classifier: Any | None = None,
        routing_policies: dict[str, dict] | None = None,
        routing_fallback_provider: str = "",
        routing_fallback_model: str = "",
        routing_confidence_threshold: float = 0.6,
        routing_model: str = "",
        routing_feedback_callback: Any | None = None,
        compact_system_prompt: str = "",
        task_embedding_index: Any | None = None,
        tool_search_manager: Any | None = None,
    ) -> None:
        self._default_model = default_model
        self._provider_pool = provider_pool
        self._semantic_classifier = semantic_classifier
        self._turn_classifier = turn_classifier
        self._routing_policies = routing_policies or {}
        self._routing_fallback_provider = routing_fallback_provider
        self._routing_fallback_model = routing_fallback_model
        self._routing_confidence_threshold = routing_confidence_threshold
        self._routing_model = routing_model
        self._routing_feedback_callback = routing_feedback_callback
        self._compact_system_prompt = compact_system_prompt
        self._task_embedding_index = task_embedding_index
        self._tool_search_manager = tool_search_manager

    @property
    def feedback_callback(self) -> Any:
        return self._routing_feedback_callback

    @property
    def provider_pool(self) -> ProviderPool | None:
        return self._provider_pool

    @property
    def fallback_provider(self) -> str:
        return self._routing_fallback_provider

    @property
    def fallback_model(self) -> str:
        return self._routing_fallback_model

    async def decide(
        self,
        *,
        user_message: str,
        turn_iteration: int,
        turn_number: int,
        api_tools: list[dict],
        pinned_target: RoutingTarget | None,
        channel: Any | None = None,
    ) -> RoutingDecision:
        """Run the routing cascade and return a decision."""
        effective_model = self._default_model
        effective_provider: Any = None
        classification: TurnClassification | None = None
        task_classification: TaskClassification | None = None
        call_type = "main"
        routing_target: RoutingTarget | None = None
        new_pinned_target: RoutingTarget | None = None

        # --- Pin continuation: reuse iteration-0 target on iteration 1+ ---
        if pinned_target is not None and turn_iteration > 0:
            routing_target = pinned_target
            effective_provider = self._provider_pool
            effective_model = routing_target.model
            call_type = f"pinned:{pinned_target.provider}/{pinned_target.model}"
            logger.info(
                "Pinned continuation: reusing iteration-0 target "
                "provider={provider} model={model} (iteration {iteration})",
                provider=routing_target.provider,
                model=routing_target.model,
                iteration=turn_iteration,
            )

        # --- Semantic routing ---
        elif self._semantic_classifier is not None and self._provider_pool is not None:
            query_embedding: list[float] | None = None
            if (
                self._task_embedding_index is not None
                and getattr(self._task_embedding_index, "is_ready", False)
            ):
                query_embedding = await self._task_embedding_index.embed_query(
                    user_message[:2000],
                )

            task_classification = self._semantic_classifier(
                user_message=user_message,
                has_tools=bool(api_tools),
                turn_iteration=turn_iteration,
                turn_number=turn_number,
                query_embedding=query_embedding,
            )
            routing_target = self._resolve_routing_target(task_classification)
            if routing_target is not None:
                effective_provider = self._provider_pool
                effective_model = routing_target.model
                call_type = f"semantic:{task_classification.task_type.value}"
                if routing_target.pin_continuation and turn_iteration == 0:
                    new_pinned_target = routing_target
            logger.info(
                "Semantic routing: task_type={task_type} stage={stage} "
                "confidence={confidence:.2f} provider={provider} model={model} reason={reason}",
                task_type=task_classification.task_type.value,
                stage=task_classification.stage,
                confidence=task_classification.confidence,
                provider=routing_target.provider if routing_target else "default",
                model=effective_model,
                reason=task_classification.reason,
            )

        # --- Legacy per-turn routing ---
        elif self._turn_classifier is not None:
            classification = self._turn_classifier(
                user_message=user_message,
                has_tools=bool(api_tools),
                turn_iteration=turn_iteration,
                turn_number=turn_number,
            )
            if classification.use_cheap_model and self._routing_model:
                effective_model = self._routing_model
                call_type = "main:routed"
            logger.info(
                "Turn routing: model={model} rule={rule} reason={reason}",
                model=effective_model,
                rule=classification.rule,
                reason=classification.reason,
            )

        # --- Per-policy overrides ---
        system_prompt_override: str | None = None
        narrowed_tools: list[dict] | None = None

        if routing_target is not None:
            if routing_target.tool_search_only:
                if self._tool_search_manager is not None:
                    narrowed_tools = self._tool_search_manager.get_tools_for_api_call()
                else:
                    from micro_x_agent_loop.tool_search import TOOL_SEARCH_SCHEMA
                    narrowed_tools = [TOOL_SEARCH_SCHEMA]
                if channel is not None:
                    from micro_x_agent_loop.agent_channel import ASK_USER_SCHEMA
                    narrowed_tools.append(ASK_USER_SCHEMA)
                logger.info(
                    "tool_search_only: narrowed tools to {count} for {model}",
                    count=len(narrowed_tools),
                    model=routing_target.model,
                )
            if routing_target.system_prompt == "compact" and self._compact_system_prompt:
                from micro_x_agent_loop.system_prompt import resolve_system_prompt
                system_prompt_override = resolve_system_prompt(self._compact_system_prompt)
                logger.info(
                    "system_prompt: using compact prompt for {model}",
                    model=routing_target.model,
                )

        return RoutingDecision(
            effective_model=effective_model,
            effective_provider=effective_provider,
            routing_target=routing_target,
            task_classification=task_classification,
            turn_classification=classification,
            call_type=call_type,
            system_prompt_override=system_prompt_override,
            narrowed_tools=narrowed_tools,
            new_pinned_target=new_pinned_target,
        )

    def _resolve_routing_target(
        self, classification: TaskClassification | None,
    ) -> RoutingTarget | None:
        """Map a task classification to a provider/model routing target.

        Applies confidence gating: if confidence is below the threshold and
        the policy would route to a different (cheaper) model, fall back to
        the main model to avoid degrading quality on uncertain classifications.
        """
        if classification is None or not self._routing_policies:
            return None

        task_type = classification.task_type.value
        policy = self._routing_policies.get(task_type)
        if policy is None:
            if self._routing_fallback_provider and self._routing_fallback_model:
                return RoutingTarget(
                    provider=self._routing_fallback_provider,
                    model=self._routing_fallback_model,
                )
            return None

        provider = policy.get("provider", self._routing_fallback_provider)
        model = policy.get("model", self._routing_fallback_model)
        tool_search_only = bool(policy.get("tool_search_only", False))
        system_prompt_policy = str(policy.get("system_prompt", ""))
        pin_continuation = bool(policy.get("pin_continuation", False))
        if not provider or not model:
            return None

        main_model = self._routing_fallback_model or self._default_model
        if (
            classification.confidence < self._routing_confidence_threshold
            and model != main_model
        ):
            logger.info(
                "Confidence gate: {confidence:.2f} < {threshold:.2f}, "
                "refusing downgrade from {main} to {target}",
                confidence=classification.confidence,
                threshold=self._routing_confidence_threshold,
                main=main_model,
                target=model,
            )
            return RoutingTarget(
                provider=self._routing_fallback_provider or provider,
                model=main_model,
            )

        if self._provider_pool is not None:
            if not self._provider_pool.should_switch_provider(
                provider,
                expected_savings_tokens=1000,
                input_price_per_mtok=3.0,
            ):
                return RoutingTarget(
                    provider=self._provider_pool.active_cache_provider,
                    model=self._routing_fallback_model or self._default_model,
                )

        return RoutingTarget(
            provider=provider,
            model=model,
            tool_search_only=tool_search_only,
            system_prompt=system_prompt_policy,
            pin_continuation=pin_continuation,
        )

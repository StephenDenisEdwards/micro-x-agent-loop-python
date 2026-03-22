"""Provider pool for multi-provider model routing.

Holds multiple initialised LLMProvider instances and dispatches
API calls to the appropriate provider by name. Tracks provider
availability and active cache state.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    pass


@dataclass
class RoutingTarget:
    """A provider + model pair for routing."""

    provider: str
    model: str
    tool_search_only: bool = False
    system_prompt: str = ""  # "compact" or "" (default/full)
    pin_continuation: bool = False


@dataclass
class ProviderStatus:
    """Tracks the health and availability of a provider."""

    available: bool = True
    last_error_time: float = 0.0
    consecutive_errors: int = 0
    cooldown_until: float = 0.0

    # Cooldown durations in seconds (exponential backoff)
    _BASE_COOLDOWN: float = 5.0
    _MAX_COOLDOWN: float = 60.0

    def mark_error(self) -> None:
        """Record an error and potentially mark provider as temporarily unavailable."""
        self.last_error_time = time.monotonic()
        self.consecutive_errors += 1
        cooldown = min(
            self._BASE_COOLDOWN * (2 ** (self.consecutive_errors - 1)),
            self._MAX_COOLDOWN,
        )
        self.cooldown_until = self.last_error_time + cooldown
        self.available = False
        logger.warning(
            f"Provider marked unavailable for {cooldown:.0f}s "
            f"(consecutive errors: {self.consecutive_errors})"
        )

    def mark_success(self) -> None:
        """Record a successful call — reset error state."""
        self.consecutive_errors = 0
        self.available = True
        self.cooldown_until = 0.0

    def is_available(self) -> bool:
        """Check if the provider is currently available."""
        if self.available:
            return True
        # Check if cooldown has expired
        if time.monotonic() >= self.cooldown_until:
            self.available = True
            return True
        return False


class ProviderPool:
    """Manages multiple LLM providers for cross-provider routing.

    The pool holds a dict of named providers and dispatches stream_chat /
    create_message calls to the requested provider.  It tracks provider
    availability and the active cache provider for cache-aware routing.
    """

    def __init__(
        self,
        providers: dict[str, Any],  # dict[str, LLMProvider]
        *,
        fallback_provider: str = "",
        cache_switch_penalty_tokens: int = 0,
    ) -> None:
        self._providers = providers
        self._status: dict[str, ProviderStatus] = {
            name: ProviderStatus() for name in providers
        }
        self._fallback_provider = fallback_provider or next(iter(providers), "")
        self._active_cache_provider: str = ""
        self._cache_switch_penalty_tokens = cache_switch_penalty_tokens
        # Extract family from each provider for same-family fallback gating
        self._families: dict[str, str] = {
            name: getattr(provider, "family", name)
            for name, provider in providers.items()
        }

    @property
    def active_cache_provider(self) -> str:
        return self._active_cache_provider

    @property
    def provider_names(self) -> list[str]:
        return list(self._providers.keys())

    def get_provider(self, name: str) -> Any:
        """Get a provider by name, or None if not found."""
        return self._providers.get(name)

    def is_available(self, provider_name: str) -> bool:
        """Check if a provider is currently available."""
        status = self._status.get(provider_name)
        if status is None:
            return False
        return status.is_available()

    def _same_family(self, name_a: str, name_b: str) -> bool:
        """Check if two providers belong to the same format family."""
        return self._families.get(name_a, name_a) == self._families.get(name_b, name_b)

    def resolve_target(
        self,
        target: RoutingTarget,
    ) -> tuple[Any, str]:
        """Resolve a routing target to a (provider_instance, model) tuple.

        Falls back to a same-family provider if the target is unavailable.
        Cross-family fallback is not attempted because message/tool formats
        are incompatible between families.

        Returns:
            (provider_instance, model_name)

        Raises:
            ValueError: If no same-family provider is available.
        """
        # Try the requested provider
        if target.provider in self._providers and self.is_available(target.provider):
            return self._providers[target.provider], target.model

        target_family = self._families.get(target.provider, target.provider)

        # Fallback — only if same family
        if (
            self._fallback_provider
            and self._fallback_provider in self._providers
            and self.is_available(self._fallback_provider)
            and self._families.get(self._fallback_provider) == target_family
        ):
            logger.warning(
                f"Provider {target.provider!r} unavailable, "
                f"falling back to {self._fallback_provider!r} (family: {target_family})"
            )
            return self._providers[self._fallback_provider], target.model

        # Try any available provider in the same family
        for name, provider in self._providers.items():
            if name == target.provider:
                continue
            if self.is_available(name) and self._families.get(name) == target_family:
                logger.warning(
                    f"Using first available same-family provider: {name!r} "
                    f"(family: {target_family})"
                )
                return provider, target.model

        raise ValueError(
            f"No same-family ({target_family}) providers available "
            f"for {target.provider!r}"
        )

    async def stream_chat(
        self,
        target: RoutingTarget,
        max_tokens: int,
        temperature: float,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        *,
        channel: Any | None = None,
    ) -> tuple[dict, list[dict], str, Any]:
        """Dispatch a stream_chat call to the target provider.

        Updates provider health status and active cache tracking.
        """
        provider, model = self.resolve_target(target)
        provider_name = target.provider

        try:
            result: tuple[dict, list[dict], str, Any] = await provider.stream_chat(
                model, max_tokens, temperature,
                system_prompt, messages, tools,
                channel=channel,
            )
            self._mark_success(provider_name)
            self._active_cache_provider = provider_name
            return result
        except Exception as ex:
            self._mark_error(provider_name)
            # Try fallback if different from the target AND same family
            if (
                provider_name != self._fallback_provider
                and self._same_family(provider_name, self._fallback_provider)
            ):
                try:
                    fb_provider, fb_model = self.resolve_target(
                        RoutingTarget(provider=self._fallback_provider, model=model)
                    )
                    fb_result: tuple[dict, list[dict], str, Any] = await fb_provider.stream_chat(
                        fb_model, max_tokens, temperature,
                        system_prompt, messages, tools,
                        channel=channel,
                    )
                    self._mark_success(self._fallback_provider)
                    self._active_cache_provider = self._fallback_provider
                    return fb_result
                except Exception:
                    self._mark_error(self._fallback_provider)
            raise ex

    async def create_message(
        self,
        target: RoutingTarget,
        max_tokens: int,
        temperature: float,
        messages: list[dict],
    ) -> tuple[str, Any]:
        """Dispatch a create_message call to the target provider."""
        provider, model = self.resolve_target(target)
        provider_name = target.provider

        try:
            cm_result: tuple[str, Any] = await provider.create_message(model, max_tokens, temperature, messages)
            self._mark_success(provider_name)
            return cm_result
        except Exception as ex:
            self._mark_error(provider_name)
            raise ex

    def convert_tools(self, tools: list[Any], *, provider_name: str = "") -> list[dict]:
        """Convert tools using the specified (or fallback) provider."""
        name = provider_name or self._fallback_provider
        provider = self._providers.get(name)
        if provider is None:
            raise ValueError(f"Provider {name!r} not found in pool")
        converted: list[dict] = provider.convert_tools(tools)
        return converted

    def should_switch_provider(
        self,
        target_provider: str,
        expected_savings_tokens: int,
        input_price_per_mtok: float,
    ) -> bool:
        """Decide whether switching providers is worth the cache rebuild cost.

        Returns True if switching is worthwhile (savings exceed cache penalty).
        """
        if not self._active_cache_provider:
            return True  # No cache to lose
        if target_provider == self._active_cache_provider:
            return True  # Same provider, no switch needed

        if self._cache_switch_penalty_tokens <= 0:
            return True  # No penalty configured

        # Estimate the cost of rebuilding the cache
        penalty_cost = self._cache_switch_penalty_tokens * input_price_per_mtok / 1_000_000
        savings_cost = expected_savings_tokens * input_price_per_mtok / 1_000_000

        return savings_cost > penalty_cost

    def _mark_success(self, provider_name: str) -> None:
        status = self._status.get(provider_name)
        if status:
            status.mark_success()

    def _mark_error(self, provider_name: str) -> None:
        status = self._status.get(provider_name)
        if status:
            status.mark_error()

"""Channel adapter protocol, trigger filtering, and built-in adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from micro_x_agent_loop.broker.runner import RunResult


@dataclass
class TriggerFilter:
    """Configurable filter for determining which messages are agent triggers.

    All fields are optional. When multiple are set, all must match (AND logic).
    An empty filter accepts all messages.
    """

    chat_ids: list[str] | None = None
    sender_ids: list[str] | None = None
    prefix: str | None = None

    def matches(self, chat_id: str | None, sender_id: str, text: str) -> str | None:
        """Check if a message matches the filter.

        Returns the prompt text (with prefix stripped) if matched, or None if filtered out.
        """
        if self.chat_ids is not None and (chat_id is None or chat_id not in self.chat_ids):
            return None
        if self.sender_ids is not None and sender_id not in self.sender_ids:
            return None
        if self.prefix is not None:
            if not text.startswith(self.prefix):
                return None
            text = text[len(self.prefix) :].strip()
        if not text:
            return None
        return text

    @property
    def is_empty(self) -> bool:
        return self.chat_ids is None and self.sender_ids is None and self.prefix is None


@dataclass
class TriggerRequest:
    """Parsed trigger from an external channel."""

    prompt: str
    sender_id: str
    channel: str
    response_target: str | None = None
    session_id: str | None = None
    config_profile: str | None = None
    metadata: dict[str, Any] | None = None


class ChannelAdapter(Protocol):
    """Protocol for messaging channel adapters (ingress + egress)."""

    @property
    def channel_name(self) -> str: ...

    @property
    def supports_webhook(self) -> bool: ...

    @property
    def supports_polling(self) -> bool: ...

    def verify_request(self, headers: dict[str, str], body: bytes) -> bool: ...

    def parse_webhook(self, payload: dict[str, Any]) -> TriggerRequest | None: ...

    async def poll_messages(self) -> list[TriggerRequest]: ...

    async def send_response(self, target: str, result: RunResult) -> bool: ...

    async def send_question(self, target: str, question: str, options: list[dict] | None = None) -> bool: ...


# -- Built-in adapters --


@dataclass
class HttpAdapter:
    """Generic HTTP trigger adapter. Every POST is intentional — no trigger filter needed."""

    auth_secret: str = ""

    @property
    def channel_name(self) -> str:
        return "http"

    @property
    def supports_webhook(self) -> bool:
        return True

    @property
    def supports_polling(self) -> bool:
        return False

    def verify_request(self, headers: dict[str, str], body: bytes) -> bool:
        if not self.auth_secret:
            return True
        auth = headers.get("authorization", "")
        return auth == f"Bearer {self.auth_secret}"

    def parse_webhook(self, payload: dict[str, Any]) -> TriggerRequest | None:
        prompt = payload.get("prompt", "").strip()
        if not prompt:
            return None
        return TriggerRequest(
            prompt=prompt,
            sender_id=payload.get("sender_id", "http"),
            channel="http",
            response_target=payload.get("callback_url"),
            session_id=payload.get("session_id"),
            config_profile=payload.get("config"),
            metadata=payload.get("metadata"),
        )

    async def poll_messages(self) -> list[TriggerRequest]:
        return []

    async def send_response(self, target: str, result: RunResult) -> bool:
        if not target:
            return False
        import httpx

        payload = {
            "status": "completed" if result.ok else "failed",
            "exit_code": result.exit_code,
            "result": result.summary,
            "error": result.stderr if not result.ok else None,
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(target, json=payload, timeout=30)
                return resp.is_success
        except Exception:
            return False

    async def send_question(self, target: str, question: str, options: list[dict] | None = None) -> bool:
        if not target:
            return False
        import httpx

        payload: dict[str, Any] = {"type": "question", "question": question}
        if options:
            payload["options"] = options
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(target, json=payload, timeout=30)
                return resp.is_success
        except Exception:
            return False


@dataclass
class LogAdapter:
    """Fallback adapter that logs results. Egress only."""

    @property
    def channel_name(self) -> str:
        return "log"

    @property
    def supports_webhook(self) -> bool:
        return False

    @property
    def supports_polling(self) -> bool:
        return False

    def verify_request(self, headers: dict[str, str], body: bytes) -> bool:
        return False

    def parse_webhook(self, payload: dict[str, Any]) -> TriggerRequest | None:
        return None

    async def poll_messages(self) -> list[TriggerRequest]:
        return []

    async def send_response(self, target: str, result: RunResult) -> bool:
        from loguru import logger

        status = "completed" if result.ok else "failed"
        logger.info(f"Run {status}: {result.summary[:200]}")
        return True

    async def send_question(self, target: str, question: str, options: list[dict] | None = None) -> bool:
        from loguru import logger

        logger.info(f"HITL question (log-only, no reply channel): {question}")
        return False


def build_trigger_filter(config: dict[str, Any] | None) -> TriggerFilter:
    """Build a TriggerFilter from a channel config's trigger_filter dict."""
    if not config:
        return TriggerFilter()
    return TriggerFilter(
        chat_ids=config.get("chat_ids"),
        sender_ids=config.get("sender_ids"),
        prefix=config.get("prefix"),
    )


def build_adapters(channels_config: dict[str, Any]) -> dict[str, ChannelAdapter]:
    """Build channel adapters from BrokerChannels config. Always includes 'log'."""
    adapters: dict[str, ChannelAdapter] = {"log": LogAdapter()}

    http_cfg = channels_config.get("http")
    if http_cfg and http_cfg.get("enabled", True):
        adapters["http"] = HttpAdapter(auth_secret=http_cfg.get("auth_secret", ""))

    return adapters

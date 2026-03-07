"""Channel adapter protocol, trigger filtering, and built-in adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass
class TelegramAdapter:
    """Telegram Bot API adapter. Supports both polling and webhook ingress."""

    bot_token: str
    trigger_filter: TriggerFilter = field(default_factory=TriggerFilter)
    webhook_secret: str = ""
    _update_offset: int = field(default=0, init=False, repr=False)

    @property
    def channel_name(self) -> str:
        return "telegram"

    @property
    def supports_webhook(self) -> bool:
        return True

    @property
    def supports_polling(self) -> bool:
        return True

    def verify_request(self, headers: dict[str, str], body: bytes) -> bool:
        if self.webhook_secret:
            return headers.get("x-telegram-bot-api-secret-token", "") == self.webhook_secret
        return bool(self.bot_token)

    def parse_webhook(self, payload: dict[str, Any]) -> TriggerRequest | None:
        return self._parse_update(payload)

    def _parse_update(self, update: dict[str, Any]) -> TriggerRequest | None:
        msg = update.get("message")
        if not msg or not msg.get("text"):
            return None
        chat_id = str(msg["chat"]["id"])
        sender_id = str(msg["from"]["id"])
        text = msg["text"]
        prompt = self.trigger_filter.matches(chat_id, sender_id, text)
        if prompt is None:
            return None
        return TriggerRequest(
            prompt=prompt,
            sender_id=sender_id,
            channel="telegram",
            response_target=chat_id,
        )

    async def poll_messages(self) -> list[TriggerRequest]:
        import httpx

        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        params: dict[str, Any] = {
            "offset": self._update_offset,
            "timeout": 1,
            "allowed_updates": ["message"],
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, params=params, timeout=10)
                data = resp.json()
        except Exception:
            return []

        if not data.get("ok"):
            return []

        results: list[TriggerRequest] = []
        for update in data.get("result", []):
            self._update_offset = update["update_id"] + 1
            req = self._parse_update(update)
            if req is not None:
                results.append(req)
        return results

    async def send_response(self, target: str, result: RunResult) -> bool:
        return await self._send_text(
            target, f"Run {'completed' if result.ok else 'failed'}:\n\n{result.summary[:4000]}"
        )

    async def send_question(self, target: str, question: str, options: list[dict] | None = None) -> bool:
        text = f"Question: {question}"
        if options:
            text += "\n\nOptions:\n" + "\n".join(
                f"- {o['label']}: {o.get('description', '')}" for o in options
            )
        return await self._send_text(target, text)

    async def _send_text(self, chat_id: str, text: str) -> bool:
        import httpx

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url, json={"chat_id": chat_id, "text": text}, timeout=30,
                )
                return resp.is_success
        except Exception:
            return False


@dataclass
class WhatsAppAdapter:
    """WhatsApp Cloud API adapter. Webhook ingress only (Cloud API has no polling endpoint)."""

    phone_number_id: str
    access_token: str
    verify_token: str = ""
    app_secret: str = ""
    trigger_filter: TriggerFilter = field(default_factory=TriggerFilter)

    @property
    def channel_name(self) -> str:
        return "whatsapp"

    @property
    def supports_webhook(self) -> bool:
        return True

    @property
    def supports_polling(self) -> bool:
        return False

    def verify_request(self, headers: dict[str, str], body: bytes) -> bool:
        if self.app_secret:
            import hashlib
            import hmac

            signature = headers.get("x-hub-signature-256", "")
            if not signature.startswith("sha256="):
                return False
            expected = hmac.new(
                self.app_secret.encode(), body, hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(signature[7:], expected)
        return bool(self.access_token)

    def parse_webhook(self, payload: dict[str, Any]) -> TriggerRequest | None:
        entry = payload.get("entry", [])
        if not entry:
            return None
        changes = entry[0].get("changes", [])
        if not changes:
            return None
        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return None

        msg = messages[0]
        if msg.get("type") != "text":
            return None

        sender_id = msg.get("from", "")
        text = msg.get("text", {}).get("body", "")
        prompt = self.trigger_filter.matches(None, sender_id, text)
        if prompt is None:
            return None
        return TriggerRequest(
            prompt=prompt,
            sender_id=sender_id,
            channel="whatsapp",
            response_target=sender_id,
        )

    async def poll_messages(self) -> list[TriggerRequest]:
        return []

    async def send_response(self, target: str, result: RunResult) -> bool:
        return await self._send_text(
            target, f"Run {'completed' if result.ok else 'failed'}:\n\n{result.summary[:4000]}"
        )

    async def send_question(self, target: str, question: str, options: list[dict] | None = None) -> bool:
        text = f"Question: {question}"
        if options:
            text += "\n\nOptions:\n" + "\n".join(
                f"- {o['label']}: {o.get('description', '')}" for o in options
            )
        return await self._send_text(target, text)

    async def _send_text(self, phone: str, text: str) -> bool:
        import httpx

        url = f"https://graph.facebook.com/v21.0/{self.phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {"body": text},
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, headers=headers, timeout=30)
                return resp.is_success
        except Exception:
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
    from loguru import logger

    adapters: dict[str, ChannelAdapter] = {"log": LogAdapter()}

    http_cfg = channels_config.get("http")
    if http_cfg and http_cfg.get("enabled", True):
        adapters["http"] = HttpAdapter(auth_secret=http_cfg.get("auth_secret", ""))

    telegram_cfg = channels_config.get("telegram")
    if telegram_cfg and telegram_cfg.get("enabled"):
        token = telegram_cfg.get("bot_token", "")
        if not token:
            logger.warning("Telegram adapter enabled but bot_token is empty — skipping")
        else:
            tf = build_trigger_filter(telegram_cfg.get("trigger_filter"))
            if tf.is_empty:
                logger.warning(
                    "Telegram adapter has an empty trigger filter — "
                    "ALL messages to the bot will be treated as agent triggers"
                )
            adapters["telegram"] = TelegramAdapter(
                bot_token=token,
                trigger_filter=tf,
                webhook_secret=telegram_cfg.get("webhook_secret", ""),
            )

    whatsapp_cfg = channels_config.get("whatsapp")
    if whatsapp_cfg and whatsapp_cfg.get("enabled"):
        phone_id = whatsapp_cfg.get("phone_number_id", "")
        access_token = whatsapp_cfg.get("access_token", "")
        if not phone_id or not access_token:
            logger.warning("WhatsApp adapter enabled but phone_number_id or access_token missing — skipping")
        else:
            tf = build_trigger_filter(whatsapp_cfg.get("trigger_filter"))
            if tf.is_empty:
                logger.warning(
                    "WhatsApp adapter has an empty trigger filter — "
                    "ALL incoming messages will be treated as agent triggers"
                )
            adapters["whatsapp"] = WhatsAppAdapter(
                phone_number_id=phone_id,
                access_token=access_token,
                verify_token=whatsapp_cfg.get("verify_token", ""),
                app_secret=whatsapp_cfg.get("app_secret", ""),
                trigger_filter=tf,
            )

    return adapters

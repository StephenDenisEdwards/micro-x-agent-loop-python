from __future__ import annotations

from collections.abc import Awaitable, Callable


class CommandRouter:
    def __init__(
        self,
        *,
        on_help: Callable[[], Awaitable[None]],
        on_rewind: Callable[[str], Awaitable[None]],
        on_checkpoint: Callable[[str], Awaitable[None]],
        on_session: Callable[[str], Awaitable[None]],
        on_voice: Callable[[str], Awaitable[None]],
        on_cost: Callable[[str], Awaitable[None]],
        on_memory: Callable[[str], Awaitable[None]],
        on_unknown: Callable[[str], None],
    ) -> None:
        self._on_help = on_help
        self._on_rewind = on_rewind
        self._on_checkpoint = on_checkpoint
        self._on_session = on_session
        self._on_voice = on_voice
        self._on_cost = on_cost
        self._on_memory = on_memory
        self._on_unknown = on_unknown

    async def try_handle(self, user_message: str) -> bool:
        trimmed = user_message.strip()
        if not trimmed.startswith("/"):
            return False

        if trimmed == "/help":
            await self._on_help()
            return True
        if trimmed.startswith("/cost"):
            await self._on_cost(trimmed)
            return True
        if trimmed.startswith("/rewind"):
            await self._on_rewind(trimmed)
            return True
        if trimmed.startswith("/checkpoint"):
            await self._on_checkpoint(trimmed)
            return True
        if trimmed.startswith("/session"):
            await self._on_session(trimmed)
            return True
        if trimmed.startswith("/voice"):
            await self._on_voice(trimmed)
            return True
        if trimmed.startswith("/memory"):
            await self._on_memory(trimmed)
            return True

        self._on_unknown(trimmed)
        return True

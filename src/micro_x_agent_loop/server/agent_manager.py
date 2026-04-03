"""AgentManager — manages Agent instances for the API server."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from micro_x_agent_loop.agent import Agent
from micro_x_agent_loop.agent_channel import BufferedChannel
from micro_x_agent_loop.agent_config import AgentConfig
from micro_x_agent_loop.compaction import NoneCompactionStrategy, SummarizeCompactionStrategy
from micro_x_agent_loop.memory import CheckpointManager, EventEmitter, MemoryStore, SessionManager
from micro_x_agent_loop.memory.event_sink import AsyncEventSink
from micro_x_agent_loop.provider import create_provider
from micro_x_agent_loop.system_prompt import get_system_prompt
from micro_x_agent_loop.tool import Tool

if TYPE_CHECKING:
    from micro_x_agent_loop.agent_channel import AgentChannel
    from micro_x_agent_loop.app_config import AppConfig


class _AgentSlot:
    """Tracks an Agent instance and its last-access time."""

    def __init__(self, agent: Agent, session_id: str) -> None:
        self.agent = agent
        self.session_id = session_id
        self.last_access = time.monotonic()

    def touch(self) -> None:
        self.last_access = time.monotonic()


class AgentManager:
    """Creates, caches, and evicts Agent instances for the API server.

    MCP tools and the memory store are shared across all agents.
    Each active session gets its own Agent with its own message history.
    """

    def __init__(
        self,
        app_config: AppConfig,
        api_key: str,
        tools: list[Tool],
        memory_store: MemoryStore | None = None,
        event_sink: AsyncEventSink | None = None,
        *,
        max_sessions: int = 10,
        session_timeout_minutes: int = 30,
    ) -> None:
        self._app_config = app_config
        self._api_key = api_key
        self._tools = tools
        self._memory_store = memory_store
        self._event_sink = event_sink
        self._max_sessions = max_sessions
        self._session_timeout_seconds = session_timeout_minutes * 60
        self._slots: dict[str, _AgentSlot] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        session_id: str,
        channel: AgentChannel | None = None,
    ) -> Agent:
        """Get an existing agent for the session, or create a new one."""
        async with self._lock:
            slot = self._slots.get(session_id)
            if slot is not None:
                slot.touch()
                # Update channel if provided (e.g., new WebSocket connection)
                if channel is not None:
                    slot.agent._channel = channel
                    slot.agent._turn_engine._channel = channel
                return slot.agent

            # Evict expired sessions before creating new ones
            self._evict_expired()

            if len(self._slots) >= self._max_sessions:
                self._evict_oldest()

            agent = self._create_agent(session_id, channel)
            await agent.initialize_session()
            self._slots[session_id] = _AgentSlot(agent, session_id)
            logger.info(f"Agent created for session {session_id[:8]}... (active={len(self._slots)})")
            return agent

    async def destroy(self, session_id: str) -> bool:
        """Destroy an agent for a session. Returns True if found."""
        async with self._lock:
            slot = self._slots.pop(session_id, None)
            if slot is None:
                return False
            await slot.agent.shutdown()
            logger.info(f"Agent destroyed for session {session_id[:8]}...")
            return True

    def list_sessions(self) -> list[dict[str, Any]]:
        """List active sessions with metadata."""
        return [
            {
                "session_id": slot.session_id,
                "idle_seconds": int(time.monotonic() - slot.last_access),
            }
            for slot in self._slots.values()
        ]

    @property
    def active_count(self) -> int:
        return len(self._slots)

    def _create_agent(self, session_id: str, channel: AgentChannel | None) -> Agent:
        app = self._app_config

        compaction_strategy: SummarizeCompactionStrategy | NoneCompactionStrategy
        if app.compaction_strategy_name == "summarize":
            compaction_model = app.compaction_model or app.model
            compaction_strategy = SummarizeCompactionStrategy(
                provider=create_provider(app.provider_name, self._api_key),
                model=compaction_model,
                threshold_tokens=app.compaction_threshold_tokens,
                protected_tail_messages=app.protected_tail_messages,
                smart_trigger_enabled=app.smart_compaction_trigger_enabled,
            )
        else:
            compaction_strategy = NoneCompactionStrategy()

        event_emitter: EventEmitter | None = None
        session_manager: SessionManager | None = None
        checkpoint_manager: CheckpointManager | None = None

        if app.memory_enabled and self._memory_store is not None:
            event_emitter = EventEmitter(self._memory_store, sink=self._event_sink)
            session_manager = SessionManager(self._memory_store, app.model, event_emitter)
            session_manager.load_or_create(session_id)
            checkpoint_manager = CheckpointManager(
                self._memory_store,
                event_emitter,
                working_directory=app.working_directory,
                enabled=app.enable_file_checkpointing,
                write_tools_only=app.checkpoint_write_tools_only,
            )

        system_prompt = get_system_prompt(
            concise_output_enabled=app.concise_output_enabled,
            task_decomposition_enabled=app.task_decomposition_enabled,
            working_directory=app.working_directory,
            compact=app.provider_name == "ollama",
        )

        summarization_model = ""
        if app.tool_result_summarization_enabled:
            summarization_model = app.tool_result_summarization_model or app.model

        return Agent(
            AgentConfig(
                model=app.model,
                max_tokens=app.max_tokens,
                temperature=app.temperature,
                api_key=self._api_key,
                provider=app.provider_name,
                tools=self._tools,
                system_prompt=system_prompt,
                max_tool_result_chars=app.max_tool_result_chars,
                max_conversation_messages=app.max_conversation_messages,
                compaction_strategy=compaction_strategy,
                memory_enabled=app.memory_enabled,
                session_id=session_id,
                session_manager=session_manager,
                checkpoint_manager=checkpoint_manager,
                event_emitter=event_emitter,
                metrics_enabled=app.metrics_enabled,
                prompt_caching_enabled=app.prompt_caching_enabled,
                tool_result_summarization_enabled=app.tool_result_summarization_enabled,
                tool_result_summarization_model=summarization_model,
                tool_result_summarization_threshold=app.tool_result_summarization_threshold,
                tool_search_enabled=app.tool_search_enabled,
                task_decomposition_enabled=app.task_decomposition_enabled,
                working_directory=app.working_directory,
                tool_formatting=app.tool_formatting,
                default_format=app.default_format,
                channel=channel or BufferedChannel(),
            )
        )

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [
            sid for sid, slot in self._slots.items()
            if (now - slot.last_access) > self._session_timeout_seconds
        ]
        for sid in expired:
            slot = self._slots.pop(sid)
            logger.info(f"Session {sid[:8]}... evicted (timeout)")
            asyncio.ensure_future(slot.agent.shutdown())

    def _evict_oldest(self) -> None:
        if not self._slots:
            return
        oldest_sid = min(self._slots, key=lambda s: self._slots[s].last_access)
        slot = self._slots.pop(oldest_sid)
        logger.info(f"Session {oldest_sid[:8]}... evicted (capacity)")
        asyncio.ensure_future(slot.agent.shutdown())

    async def shutdown_all(self) -> None:
        """Shut down all active agents."""
        for slot in self._slots.values():
            await slot.agent.shutdown()
        self._slots.clear()

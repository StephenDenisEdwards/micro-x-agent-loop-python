"""FastAPI application for the Agent API Server."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from micro_x_agent_loop.agent_channel import BufferedChannel
from micro_x_agent_loop.app_config import AppConfig, load_json_config, parse_app_config, resolve_runtime_env
from micro_x_agent_loop.logging_config import setup_logging
from micro_x_agent_loop.mcp.mcp_manager import McpManager
from micro_x_agent_loop.memory import MemoryStore, SessionManager, prune_memory
from micro_x_agent_loop.memory.event_sink import AsyncEventSink
from micro_x_agent_loop.server.agent_manager import AgentManager
from micro_x_agent_loop.server.ws_channel import WebSocketChannel


# Module-level state shared between lifespan and route handlers.
_state: dict[str, Any] = {}


def create_app(
    *,
    config_path: str | None = None,
    api_secret: str | None = None,
    cors_origins: list[str] | None = None,
    max_sessions: int = 10,
    session_timeout_minutes: int = 30,
    broker_enabled: bool = False,
) -> FastAPI:
    """Create and configure the FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        # -- Startup --
        raw_config, _ = load_json_config(config_path)
        app_config = parse_app_config(raw_config)
        env = resolve_runtime_env(app_config.provider_name)
        setup_logging(level=app_config.log_level, consumers=app_config.log_consumers)

        mcp_manager: McpManager | None = None
        tools: list = []
        if app_config.mcp_server_configs:
            mcp_manager = McpManager(app_config.mcp_server_configs)
            tools = await mcp_manager.connect_all()

        memory_store: MemoryStore | None = None
        event_sink: AsyncEventSink | None = None
        if app_config.memory_enabled:
            db_path = Path(app_config.memory_db_path)
            if not db_path.is_absolute():
                db_path = Path.cwd() / db_path
            memory_store = MemoryStore(str(db_path))
            event_sink = AsyncEventSink(memory_store)
            await event_sink.start()
            prune_memory(
                memory_store,
                max_sessions=app_config.memory_max_sessions,
                max_messages_per_session=app_config.memory_max_messages_per_session,
                retention_days=app_config.memory_retention_days,
            )

        agent_manager = AgentManager(
            app_config=app_config,
            api_key=env.provider_api_key,
            tools=tools,
            memory_store=memory_store,
            event_sink=event_sink,
            max_sessions=max_sessions,
            session_timeout_minutes=session_timeout_minutes,
        )

        _state.update({
            "app_config": app_config,
            "raw_config": raw_config,
            "env": env,
            "mcp_manager": mcp_manager,
            "memory_store": memory_store,
            "event_sink": event_sink,
            "agent_manager": agent_manager,
            "tools": tools,
        })

        # -- Broker integration --
        broker_tasks: list[asyncio.Task] = []
        polling_ingresses: list = []

        if broker_enabled:
            from micro_x_agent_loop.broker.channels import build_adapters
            from micro_x_agent_loop.broker.dispatcher import RunDispatcher
            from micro_x_agent_loop.broker.polling import PollingIngress
            from micro_x_agent_loop.broker.response_router import ResponseRouter
            from micro_x_agent_loop.broker.scheduler import Scheduler
            from micro_x_agent_loop.broker.store import BrokerStore
            from micro_x_agent_loop.server.broker_routes import create_broker_router

            broker_db_path = raw_config.get("BrokerDatabase", ".micro_x/broker.db")
            broker_store = BrokerStore(broker_db_path)

            channels_config = raw_config.get("BrokerChannels", {})
            adapters = build_adapters(channels_config)
            response_router = ResponseRouter(adapters)

            host = os.environ.get("SERVER_HOST", "127.0.0.1")
            port = os.environ.get("SERVER_PORT", "8321")
            broker_url = f"http://{host}:{port}"

            max_concurrent = int(raw_config.get("BrokerMaxConcurrentRuns", 2))
            dispatcher = RunDispatcher(
                broker_store,
                response_router,
                max_concurrent_runs=max_concurrent,
                broker_url=broker_url,
            )

            poll_interval = int(raw_config.get("BrokerPollIntervalSeconds", 5))
            recovery_policy = str(raw_config.get("BrokerRecoveryPolicy", "skip"))
            scheduler = Scheduler(
                broker_store,
                dispatcher,
                poll_interval=poll_interval,
                recovery_policy=recovery_policy,
            )

            # Mount broker routes
            broker_router = create_broker_router(broker_store, dispatcher, adapters)
            app.include_router(broker_router)

            # Start scheduler
            broker_tasks.append(asyncio.create_task(scheduler.start(), name="scheduler"))

            # Start polling ingress for adapters that support it
            for name, adapter in adapters.items():
                if adapter.supports_polling:
                    adapter_poll = channels_config.get(name, {}).get("poll_interval", 10)
                    ingress = PollingIngress(
                        adapter, dispatcher, broker_store,
                        poll_interval=adapter_poll,
                    )
                    polling_ingresses.append(ingress)
                    broker_tasks.append(asyncio.create_task(
                        ingress.start(), name=f"polling-{name}",
                    ))

            _state.update({
                "broker_store": broker_store,
                "broker_dispatcher": dispatcher,
                "broker_scheduler": scheduler,
                "broker_adapters": adapters,
                "broker_polling_ingresses": polling_ingresses,
            })

            logger.info(
                f"Broker enabled: jobs={len(broker_store.list_jobs())}, "
                f"channels={list(adapters.keys())}, "
                f"max_concurrent_runs={max_concurrent}"
            )

        logger.info(
            f"API server started: model={app_config.model}, "
            f"tools={len(tools)}, memory={'on' if app_config.memory_enabled else 'off'}, "
            f"max_sessions={max_sessions}, broker={'on' if broker_enabled else 'off'}"
        )

        yield

        # -- Shutdown --

        # Stop broker components
        if broker_enabled:
            scheduler = _state.get("broker_scheduler")
            if scheduler:
                scheduler.stop()
            for ingress in polling_ingresses:
                ingress.stop()

            # Wait for broker tasks to finish
            for task in broker_tasks:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            dispatcher = _state.get("broker_dispatcher")
            if dispatcher:
                await dispatcher.wait_for_all()

            broker_store = _state.get("broker_store")
            if broker_store:
                broker_store.close()

        await agent_manager.shutdown_all()
        if mcp_manager:
            await mcp_manager.close()
        if event_sink:
            await event_sink.close()
        _state.clear()
        logger.info("API server shut down")

    app = FastAPI(title="micro-x-agent API", docs_url="/docs", redoc_url=None, lifespan=lifespan)

    # CORS
    origins = cors_origins or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Auth middleware
    secret = api_secret or os.environ.get("SERVER_API_SECRET", "")
    if secret:
        @app.middleware("http")
        async def auth_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
            if request.url.path in ("/api/health", "/docs", "/openapi.json"):
                return await call_next(request)
            auth = request.headers.get("authorization", "")
            if auth != f"Bearer {secret}":
                return Response(
                    status_code=401,
                    content='{"error": "Unauthorized"}',
                    media_type="application/json",
                )
            return await call_next(request)

    # -- Health ---------------------------------------------------------------

    @app.get("/api/health")
    async def health() -> dict:
        agent_manager: AgentManager | None = _state.get("agent_manager")
        result: dict[str, Any] = {
            "status": "ok",
            "active_sessions": agent_manager.active_count if agent_manager else 0,
            "tools": len(_state.get("tools", [])),
            "memory_enabled": bool(_state.get("app_config") and _state["app_config"].memory_enabled),
        }
        # Include broker status if enabled
        broker_store = _state.get("broker_store")
        if broker_store:
            from micro_x_agent_loop.broker.store import BrokerStore

            jobs = broker_store.list_jobs()
            dispatcher = _state.get("broker_dispatcher")
            result["broker"] = {
                "enabled": True,
                "jobs_total": len(jobs),
                "jobs_enabled": sum(1 for j in jobs if j["enabled"]),
                "active_runs": dispatcher.active_run_count if dispatcher else 0,
                "channels": list(_state.get("broker_adapters", {}).keys()),
            }
        return result

    # -- Sessions -------------------------------------------------------------

    @app.post("/api/sessions", response_model=None)
    async def create_session():  # type: ignore[no-untyped-def]
        memory_store: MemoryStore | None = _state.get("memory_store")
        app_config: AppConfig | None = _state.get("app_config")
        if memory_store is None or app_config is None or not app_config.memory_enabled:
            return Response(
                status_code=400,
                content='{"error": "Memory is not enabled"}',
                media_type="application/json",
            )
        from micro_x_agent_loop.memory import EventEmitter
        event_sink: AsyncEventSink | None = _state.get("event_sink")
        emitter = EventEmitter(memory_store, sink=event_sink)
        sm = SessionManager(memory_store, app_config.model, emitter)
        session_id = sm.create_session()
        return {"session_id": session_id}

    @app.get("/api/sessions")
    async def list_sessions() -> dict:
        memory_store: MemoryStore | None = _state.get("memory_store")
        app_config: AppConfig | None = _state.get("app_config")
        if memory_store is None or app_config is None or not app_config.memory_enabled:
            return {"sessions": []}
        from micro_x_agent_loop.memory import EventEmitter
        emitter = EventEmitter(memory_store, sink=_state.get("event_sink"))
        sm = SessionManager(memory_store, app_config.model, emitter)
        sessions = sm.list_sessions(limit=50)
        return {"sessions": sessions}

    @app.get("/api/sessions/{session_id}", response_model=None)
    async def get_session(session_id: str):  # type: ignore[no-untyped-def]
        memory_store: MemoryStore | None = _state.get("memory_store")
        app_config: AppConfig | None = _state.get("app_config")
        if memory_store is None or app_config is None or not app_config.memory_enabled:
            return Response(status_code=404, content='{"error": "Not found"}', media_type="application/json")
        from micro_x_agent_loop.memory import EventEmitter
        emitter = EventEmitter(memory_store, sink=_state.get("event_sink"))
        sm = SessionManager(memory_store, app_config.model, emitter)
        session = sm.get_session(session_id)
        if session is None:
            return Response(status_code=404, content='{"error": "Session not found"}', media_type="application/json")
        return session

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str) -> dict:
        agent_manager: AgentManager | None = _state.get("agent_manager")
        if agent_manager:
            await agent_manager.destroy(session_id)
        return {"status": "deleted", "session_id": session_id}

    @app.get("/api/sessions/{session_id}/messages", response_model=None)
    async def get_messages(session_id: str):  # type: ignore[no-untyped-def]
        memory_store: MemoryStore | None = _state.get("memory_store")
        app_config: AppConfig | None = _state.get("app_config")
        if memory_store is None or app_config is None or not app_config.memory_enabled:
            return Response(status_code=404, content='{"error": "Not found"}', media_type="application/json")
        from micro_x_agent_loop.memory import EventEmitter
        emitter = EventEmitter(memory_store, sink=_state.get("event_sink"))
        sm = SessionManager(memory_store, app_config.model, emitter)
        messages = sm.load_messages(session_id)
        return {"session_id": session_id, "messages": messages}

    # -- Chat (non-streaming) -------------------------------------------------

    @app.post("/api/chat", response_model=None)
    async def chat(request: Request):  # type: ignore[no-untyped-def]
        agent_manager: AgentManager | None = _state.get("agent_manager")
        if agent_manager is None:
            return Response(status_code=503, content='{"error": "Not ready"}', media_type="application/json")

        try:
            data = await request.json()
        except Exception:
            return Response(status_code=400, content='{"error": "Invalid JSON"}', media_type="application/json")

        message = data.get("message", "").strip()
        session_id = data.get("session_id", "").strip()

        if not message:
            return Response(status_code=400, content='{"error": "Message required"}', media_type="application/json")

        if not session_id:
            memory_store: MemoryStore | None = _state.get("memory_store")
            app_config: AppConfig | None = _state.get("app_config")
            if memory_store and app_config and app_config.memory_enabled:
                from micro_x_agent_loop.memory import EventEmitter
                emitter = EventEmitter(memory_store, sink=_state.get("event_sink"))
                sm = SessionManager(memory_store, app_config.model, emitter)
                session_id = sm.create_session()
            else:
                import uuid
                session_id = str(uuid.uuid4())

        channel = BufferedChannel()
        agent = await agent_manager.get_or_create(session_id, channel=channel)
        await agent.run(message)

        return {
            "session_id": session_id,
            "response": channel.text,
            "errors": channel.errors if channel.errors else None,
        }

    # -- WebSocket (streaming) ------------------------------------------------

    @app.websocket("/api/ws/{session_id}")
    async def websocket_chat(ws: WebSocket, session_id: str) -> None:
        agent_manager: AgentManager | None = _state.get("agent_manager")
        if agent_manager is None:
            await ws.close(code=1011, reason="Server not ready")
            return

        await ws.accept()
        channel = WebSocketChannel(ws)
        agent = await agent_manager.get_or_create(session_id, channel=channel)

        logger.info(f"WebSocket connected: session={session_id[:8]}...")

        try:
            while True:
                data = await ws.receive_json()
                msg_type = data.get("type", "")

                if msg_type == "message":
                    text = data.get("text", "").strip()
                    if text:
                        await agent.run(text)
                        channel.emit_turn_complete({})

                elif msg_type == "answer":
                    question_id = data.get("question_id", "")
                    answer_text = data.get("text", "")
                    channel.receive_answer(question_id, answer_text)

                elif msg_type == "ping":
                    await ws.send_json({"type": "pong"})

        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected: session={session_id[:8]}...")
        except Exception as ex:
            logger.warning(f"WebSocket error: session={session_id[:8]}..., error={ex}")

    return app


async def run_server(
    *,
    config_path: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8321,
    api_secret: str | None = None,
    cors_origins: list[str] | None = None,
    max_sessions: int = 10,
    session_timeout_minutes: int = 30,
    broker_enabled: bool = False,
) -> None:
    """Start the API server. Blocks until shutdown."""
    import uvicorn

    app = create_app(
        config_path=config_path,
        api_secret=api_secret,
        cors_origins=cors_origins,
        max_sessions=max_sessions,
        session_timeout_minutes=session_timeout_minutes,
        broker_enabled=broker_enabled,
    )

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    logger.info(f"Starting API server on {host}:{port}")
    await server.serve()

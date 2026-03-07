"""FastAPI webhook server for external trigger ingress."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, Request, Response
from loguru import logger

from micro_x_agent_loop.broker.channels import ChannelAdapter
from micro_x_agent_loop.broker.dispatcher import RunDispatcher
from micro_x_agent_loop.broker.store import BrokerStore


class WebhookServer:
    """FastAPI-based webhook server running inside the broker."""

    def __init__(
        self,
        store: BrokerStore,
        dispatcher: RunDispatcher,
        adapters: dict[str, ChannelAdapter],
        *,
        host: str = "127.0.0.1",
        port: int = 8321,
    ) -> None:
        self._store = store
        self._dispatcher = dispatcher
        self._adapters = adapters
        self._host = host
        self._port = port
        self._server: asyncio.Server | None = None

        self._app = FastAPI(title="micro-x-agent broker", docs_url=None, redoc_url=None)
        self._register_routes()

    def _register_routes(self) -> None:
        app = self._app

        @app.get("/api/health")
        async def health() -> dict[str, Any]:
            jobs = self._store.list_jobs()
            enabled = sum(1 for j in jobs if j["enabled"])
            return {
                "status": "ok",
                "jobs_total": len(jobs),
                "jobs_enabled": enabled,
                "active_runs": self._dispatcher.active_run_count,
                "channels": list(self._adapters.keys()),
            }

        @app.get("/api/jobs")
        async def list_jobs() -> list[dict[str, Any]]:
            return self._store.list_jobs()

        @app.get("/api/runs/{run_id}")
        async def get_run(run_id: str) -> dict[str, Any] | Response:
            run = self._store.get_run(run_id)
            if run is None:
                return Response(status_code=404, content='{"error": "Run not found"}', media_type="application/json")
            return run

        @app.post("/api/trigger/{channel}")
        async def trigger(channel: str, request: Request) -> dict[str, Any] | Response:
            adapter = self._adapters.get(channel)
            if adapter is None:
                return Response(
                    status_code=404,
                    content=f'{{"error": "Unknown channel: {channel}"}}',
                    media_type="application/json",
                )

            if not adapter.supports_webhook:
                return Response(
                    status_code=400,
                    content=f'{{"error": "Channel {channel} does not support webhooks"}}',
                    media_type="application/json",
                )

            # Read and verify
            body = await request.body()
            headers = dict(request.headers)
            if not adapter.verify_request(headers, body):
                return Response(status_code=401, content='{"error": "Unauthorized"}', media_type="application/json")

            # Parse trigger
            try:
                payload = await request.json()
            except Exception:
                return Response(
                    status_code=400,
                    content='{"error": "Invalid JSON"}',
                    media_type="application/json",
                )

            trigger_req = adapter.parse_webhook(payload)
            if trigger_req is None:
                # Not actionable (e.g., status update) — acknowledge silently
                return {"status": "ignored"}

            # Check capacity
            if self._dispatcher.at_capacity:
                return Response(
                    status_code=503,
                    content='{"error": "At capacity, try again later"}',
                    media_type="application/json",
                )

            # Create run and dispatch
            run_id = self._store.create_run(
                job_id=None,
                trigger_source=channel,
                prompt=trigger_req.prompt,
                session_id=trigger_req.session_id,
            )

            response_target = trigger_req.response_target or trigger_req.sender_id
            self._dispatcher.dispatch(
                run_id=run_id,
                prompt=trigger_req.prompt,
                config_profile=trigger_req.config_profile,
                session_id=trigger_req.session_id,
                response_channel=channel,
                response_target=response_target,
            )

            logger.info(
                f"Webhook trigger from {channel}: run_id={run_id[:8]}, "
                f"sender={trigger_req.sender_id}, prompt={trigger_req.prompt[:60]!r}"
            )

            return {
                "status": "dispatched",
                "run_id": run_id,
            }

    async def start(self) -> None:
        """Start the server. Blocks until stop() is called."""
        import uvicorn

        config = uvicorn.Config(
            self._app,
            host=self._host,
            port=self._port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        logger.info(f"Webhook server starting on {self._host}:{self._port}")
        await server.serve()

    async def stop(self) -> None:
        """Signal the server to stop."""
        # uvicorn.Server.serve() responds to KeyboardInterrupt / signal;
        # the BrokerService signal handler handles this via scheduler.stop()
        pass

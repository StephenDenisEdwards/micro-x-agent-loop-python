"""FastAPI webhook server for external trigger ingress."""

from __future__ import annotations

import asyncio
import json
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
        api_secret: str | None = None,
    ) -> None:
        self._store = store
        self._dispatcher = dispatcher
        self._adapters = adapters
        self._host = host
        self._port = port
        self._api_secret = api_secret
        self._server: asyncio.Server | None = None

        self._app = FastAPI(title="micro-x-agent broker", docs_url=None, redoc_url=None)
        if api_secret:
            self._register_auth_middleware()
        self._register_routes()

    def _register_auth_middleware(self) -> None:
        """Add bearer token auth to all endpoints except /api/health."""
        secret = self._api_secret

        @self._app.middleware("http")
        async def auth_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
            if request.url.path != "/api/health":
                auth = request.headers.get("authorization", "")
                if auth != f"Bearer {secret}":
                    return Response(
                        status_code=401,
                        content='{"error": "Unauthorized"}',
                        media_type="application/json",
                    )
            return await call_next(request)

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

        @app.post("/api/runs/{run_id}/questions")
        async def post_question(run_id: str, request: Request) -> dict[str, Any] | Response:
            """Agent subprocess posts a question for async human-in-the-loop."""
            run = self._store.get_run(run_id)
            if run is None:
                return Response(
                    status_code=404,
                    content='{"error": "Run not found"}',
                    media_type="application/json",
                )

            try:
                data = await request.json()
            except Exception:
                return Response(
                    status_code=400,
                    content='{"error": "Invalid JSON"}',
                    media_type="application/json",
                )

            question_text = data.get("question", "").strip()
            if not question_text:
                return Response(
                    status_code=400,
                    content='{"error": "Question text required"}',
                    media_type="application/json",
                )

            options = data.get("options")

            # Determine HITL timeout from job config
            timeout = 300
            if run.get("job_id"):
                job = self._store.get_job(run["job_id"])
                if job:
                    timeout = job.get("hitl_timeout_seconds") or 300

            options_json = json.dumps(options) if options else None
            qid = self._store.create_question(
                run_id=run_id,
                question_text=question_text,
                options=options_json,
                timeout_seconds=timeout,
            )

            # Route question to channel adapter
            channel = run.get("response_channel", "log")
            target = run.get("response_target", "")
            adapter = self._adapters.get(channel)
            if adapter:
                try:
                    await adapter.send_question(target or "", question_text, options)
                except Exception as ex:
                    logger.warning(f"Failed to route HITL question via {channel}: {ex}")

            logger.info(f"HITL question created: qid={qid[:8]}, run={run_id[:8]}, timeout={timeout}s")
            return {"question_id": qid, "timeout_seconds": timeout}

        @app.get("/api/runs/{run_id}/questions/{question_id}")
        async def get_question(run_id: str, question_id: str) -> dict[str, Any] | Response:
            """Agent subprocess polls for answer."""
            q = self._store.get_question(question_id)
            if q is None or q["run_id"] != run_id:
                return Response(
                    status_code=404,
                    content='{"error": "Question not found"}',
                    media_type="application/json",
                )
            return q

        @app.post("/api/runs/{run_id}/questions/{question_id}/answer")
        async def answer_question(run_id: str, question_id: str, request: Request) -> dict[str, Any] | Response:
            """External client or channel adapter posts an answer."""
            q = self._store.get_question(question_id)
            if q is None or q["run_id"] != run_id:
                return Response(
                    status_code=404,
                    content='{"error": "Question not found"}',
                    media_type="application/json",
                )

            if q["status"] != "pending":
                return Response(
                    status_code=409,
                    content=json.dumps({"error": f"Question is already {q['status']}"}),
                    media_type="application/json",
                )

            try:
                data = await request.json()
            except Exception:
                return Response(
                    status_code=400,
                    content='{"error": "Invalid JSON"}',
                    media_type="application/json",
                )

            answer = data.get("answer", "").strip()
            if not answer:
                return Response(
                    status_code=400,
                    content='{"error": "Answer text required"}',
                    media_type="application/json",
                )

            success = self._store.answer_question(question_id, answer=answer)
            if not success:
                return Response(
                    status_code=409,
                    content='{"error": "Question is no longer pending"}',
                    media_type="application/json",
                )

            logger.info(f"HITL answer received: qid={question_id[:8]}, run={run_id[:8]}")
            return {"status": "answered"}

        @app.get("/api/runs/{run_id}/questions")
        async def list_questions(run_id: str) -> dict[str, Any] | Response:
            """List pending questions for a run."""
            q = self._store.get_pending_question(run_id)
            return {"pending_question": q}

        @app.get("/api/trigger/{channel}")
        async def trigger_verify(channel: str, request: Request) -> Response:
            """Handle webhook verification challenges (e.g., WhatsApp/Meta hub.verify_token)."""
            mode = request.query_params.get("hub.mode")
            verify_token = request.query_params.get("hub.verify_token")
            challenge = request.query_params.get("hub.challenge", "")

            if mode != "subscribe":
                return Response(status_code=404, content='{"error": "Not found"}', media_type="application/json")

            adapter = self._adapters.get(channel)
            if adapter is None:
                return Response(status_code=404, content='{"error": "Unknown channel"}', media_type="application/json")

            expected_token = getattr(adapter, "verify_token", None)
            if expected_token and verify_token == expected_token:
                logger.info(f"Webhook verification successful for {channel}")
                return Response(content=challenge, media_type="text/plain")

            return Response(status_code=403, content='{"error": "Verification failed"}', media_type="application/json")

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

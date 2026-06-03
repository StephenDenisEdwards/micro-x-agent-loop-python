"""OpenTelemetry export for observability events (PLAN-observability Phase 4).

Opt-in (``OtelEnabled`` + ``OtelEndpoint``). Subscribes to the
``ObservabilityEmitter`` and maps ``metric.api_call`` / ``metric.tool_execution``
events to spans following the OpenTelemetry GenAI semantic conventions
(https://opentelemetry.io/docs/specs/semconv/gen-ai/), parented under a
per-session root span.

The OTel SDK is an *optional* dependency (``pip install -e ".[otel]"``). The
attribute-mapping logic is a pure function (`build_span_spec`) testable without
the SDK; the SDK glue (`OtelExporter`) imports lazily and no-ops if the SDK is
absent or construction fails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass
class SpanSpec:
    """A backend-agnostic description of one span (SDK-free, so it is testable)."""

    name: str
    kind: str  # "llm" | "tool"
    session_id: str
    attributes: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0


def _meta_session(payload: dict) -> str:
    sid = payload.get("session_id")
    return str(sid) if sid else ""


def build_span_spec(event_type: str, payload: dict) -> SpanSpec | None:
    """Map an observability event to a span spec, or None if it isn't span-worthy.

    Covers the two duration-bearing metric events; other events (decisions,
    config) are span *attributes* on their parent turn rather than spans.
    """
    if event_type == "metric.api_call":
        model = str(payload.get("model", ""))
        return SpanSpec(
            name=f"chat {model}".strip(),
            kind="llm",
            session_id=_meta_session(payload),
            duration_ms=float(payload.get("duration_ms", 0) or 0),
            attributes={
                "gen_ai.operation.name": "chat",
                "gen_ai.system": payload.get("provider", ""),
                "gen_ai.request.model": model,
                "gen_ai.response.model": model,
                "gen_ai.usage.input_tokens": int(payload.get("input_tokens", 0) or 0),
                "gen_ai.usage.output_tokens": int(payload.get("output_tokens", 0) or 0),
                "gen_ai.response.finish_reasons": str(payload.get("stop_reason", "")),
                "micro_x.call_type": payload.get("call_type", ""),
                "micro_x.cache_read_tokens": int(payload.get("cache_read_input_tokens", 0) or 0),
                "micro_x.cost_usd": float(payload.get("estimated_cost_usd", 0) or 0),
                "micro_x.turn": int(payload.get("turn_number", 0) or 0),
            },
        )
    if event_type == "metric.tool_execution":
        tool = str(payload.get("tool_name", ""))
        return SpanSpec(
            name=f"execute_tool {tool}".strip(),
            kind="tool",
            session_id=_meta_session(payload),
            duration_ms=float(payload.get("duration_ms", 0) or 0),
            attributes={
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": tool,
                "micro_x.result_chars": int(payload.get("result_chars", 0) or 0),
                "micro_x.is_error": bool(payload.get("is_error", False)),
                "micro_x.was_summarized": bool(payload.get("was_summarized", False)),
                "micro_x.turn": int(payload.get("turn_number", 0) or 0),
            },
        )
    return None


class OtelExporter:
    """Subscriber that emits OTel spans for observability events.

    A root span per session is created lazily and ended on
    ``metric.session_summary``. Child LLM/tool spans are back-dated by their
    measured duration so traces show real timings.
    """

    def __init__(self, endpoint: str, *, service_name: str = "micro-x-agent") -> None:
        import time

        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        self._time = time
        self._trace = trace
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        self._provider = provider
        self._tracer = provider.get_tracer("micro_x_agent_loop.observability")
        self._session_spans: dict[str, Any] = {}

    def _root(self, session_id: str) -> Any:
        span = self._session_spans.get(session_id)
        if span is None:
            span = self._tracer.start_span(f"session {session_id}")
            self._session_spans[session_id] = span
        return span

    def __call__(self, event_type: str, payload: dict) -> None:
        try:
            if event_type == "metric.session_summary":
                sid = _meta_session(payload)
                span = self._session_spans.pop(sid, None)
                if span is not None:
                    span.end()
                return
            spec = build_span_spec(event_type, payload)
            if spec is None or not spec.session_id:
                return
            parent = self._root(spec.session_id)
            ctx = self._trace.set_span_in_context(parent)
            end_ns = self._time.time_ns()
            start_ns = end_ns - int(spec.duration_ms * 1_000_000)
            child = self._tracer.start_span(spec.name, context=ctx, start_time=start_ns)
            for k, v in spec.attributes.items():
                child.set_attribute(k, v)
            child.end(end_time=end_ns)
        except Exception as ex:  # never let telemetry break the agent
            logger.warning(f"OTel export failed for {event_type}: {ex}")

    def shutdown(self) -> None:
        for span in self._session_spans.values():
            try:
                span.end()
            except Exception:
                pass
        self._session_spans.clear()
        try:
            self._provider.shutdown()
        except Exception:
            pass


def build_otel_exporter(endpoint: str, *, service_name: str = "micro-x-agent") -> OtelExporter | None:
    """Construct an exporter, or return None if the OTel SDK isn't installed."""
    try:
        return OtelExporter(endpoint, service_name=service_name)
    except ImportError:
        logger.warning("OtelEnabled=true but the OTel SDK is not installed; run: pip install -e \".[otel]\"")
        return None
    except Exception as ex:
        logger.warning(f"OTel exporter init failed: {ex}")
        return None

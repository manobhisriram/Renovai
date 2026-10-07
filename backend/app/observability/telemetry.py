"""LLM telemetry sinks.

Every model call is (1) counted in Prometheus, (2) persisted to the ``llm_calls`` table (the local,
always-available fallback), and optionally (3) shipped to Langfuse and (4) emitted as an OpenTelemetry
span. Sinks never raise into the request path.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from app.config import Settings
from app.observability import metrics
from app.observability.context import node_var, project_id_var, request_id_var, run_id_var

log = logging.getLogger(__name__)


@dataclass
class LLMCallRecord:
    provider: str
    model: str
    tier: str
    task: str
    latency_ms: int
    success: bool
    input_tokens: int | None = None
    output_tokens: int | None = None
    est_cost_usd: float | None = None
    error: str | None = None
    input_preview: str | None = None
    output_preview: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class TelemetrySink(Protocol):
    def record(self, rec: LLMCallRecord) -> None: ...


def estimate_cost(settings: Settings, model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    """Cost estimate from user-supplied pricing (LLM_PRICING_JSON). Returns None when pricing is unknown."""
    if input_tokens is None or output_tokens is None:
        return None
    for prefix, price in settings.llm_pricing.items():
        if model.startswith(prefix):
            return round((input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000, 6)
    return None


class PrometheusSink:
    def record(self, rec: LLMCallRecord) -> None:
        metrics.LLM_CALLS.labels(rec.provider, rec.model, rec.tier, "ok" if rec.success else "error").inc()
        metrics.LLM_LATENCY.labels(rec.model).observe(rec.latency_ms / 1000)
        if rec.input_tokens:
            metrics.LLM_TOKENS.labels(rec.model, "input").inc(rec.input_tokens)
        if rec.output_tokens:
            metrics.LLM_TOKENS.labels(rec.model, "output").inc(rec.output_tokens)


class DatabaseSink:
    def __init__(self, session_factory: Any):
        self._sf = session_factory

    def record(self, rec: LLMCallRecord) -> None:
        from app.database.models import LLMCall

        with self._sf() as session:
            session.add(LLMCall(
                project_id=_none_if_dash(project_id_var.get()), run_id=_none_if_dash(run_id_var.get()),
                request_id=_none_if_dash(request_id_var.get()), node=_none_if_dash(node_var.get()),
                task=rec.task, tier=rec.tier, provider=rec.provider, model=rec.model,
                latency_ms=rec.latency_ms, input_tokens=rec.input_tokens, output_tokens=rec.output_tokens,
                est_cost_usd=rec.est_cost_usd, success=rec.success, error=(rec.error or None) and rec.error[:500],
            ))
            session.commit()


class LangfuseSink:
    """Ships generations to Langfuse through its public ingestion API.

    NOTE: written against the documented ingestion endpoint; it has not been exercised against a live
    Langfuse instance from this repository's CI. Enable with LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY.
    """

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        assert settings.langfuse_public_key and settings.langfuse_secret_key
        self._url = settings.langfuse_host.rstrip("/") + "/api/public/ingestion"
        self._auth = (settings.langfuse_public_key, settings.langfuse_secret_key.get_secret_value())
        self._client = client or httpx.Client(timeout=5.0)

    def record(self, rec: LLMCallRecord) -> None:
        now = datetime.now(UTC)
        trace_id = request_id_var.get()
        event = {
            "id": uuid.uuid4().hex,
            "type": "generation-create",
            "timestamp": now.isoformat(),
            "body": {
                "id": uuid.uuid4().hex,
                "traceId": trace_id if trace_id != "-" else None,
                "name": rec.task,
                "model": rec.model,
                "startTime": now.isoformat(),
                "endTime": now.isoformat(),
                "usage": {"input": rec.input_tokens, "output": rec.output_tokens},
                "level": "DEFAULT" if rec.success else "ERROR",
                "statusMessage": rec.error,
                "metadata": {"tier": rec.tier, "provider": rec.provider, "latency_ms": rec.latency_ms,
                             "project_id": project_id_var.get(), "node": node_var.get()},
            },
        }
        self._client.post(self._url, json={"batch": [event]}, auth=self._auth)


class OtelSink:
    """Emits one span per LLM call when an OpenTelemetry SDK + exporter are installed/configured."""

    def __init__(self) -> None:
        from opentelemetry import trace  # optional dependency

        self._tracer = trace.get_tracer("renovai.llm")

    def record(self, rec: LLMCallRecord) -> None:
        with self._tracer.start_as_current_span(f"llm.{rec.task}") as span:
            span.set_attribute("llm.model", rec.model)
            span.set_attribute("llm.tier", rec.tier)
            span.set_attribute("llm.latency_ms", rec.latency_ms)
            span.set_attribute("llm.success", rec.success)
            if rec.input_tokens is not None:
                span.set_attribute("llm.input_tokens", rec.input_tokens)
            if rec.output_tokens is not None:
                span.set_attribute("llm.output_tokens", rec.output_tokens)


class Telemetry:
    def __init__(self, sinks: list[TelemetrySink]):
        self.sinks = sinks

    def record(self, rec: LLMCallRecord) -> None:
        for sink in self.sinks:
            try:
                sink.record(rec)
            except Exception as exc:  # telemetry must never break a request
                log.warning("telemetry sink %s failed: %s", type(sink).__name__, type(exc).__name__)


def build_telemetry(settings: Settings, session_factory: Any) -> Telemetry:
    sinks: list[TelemetrySink] = [PrometheusSink(), DatabaseSink(session_factory)]
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        sinks.append(LangfuseSink(settings))
    if settings.otel_exporter_otlp_endpoint:
        try:
            sinks.append(OtelSink())
        except ImportError:
            log.warning("OTEL_EXPORTER_OTLP_ENDPOINT is set but opentelemetry is not installed (pip install -r requirements-otel.txt)")
    return Telemetry(sinks)


def _none_if_dash(v: str) -> str | None:
    return None if v in ("-", "", None) else v

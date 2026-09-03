"""
app/telemetry.py
================
OpenTelemetry wiring — traces + metrics for the API, the model wrapper,
the spend guards and the deterministic core paths.

OFF by default and a genuine no-op when off: the OTel API returns no-op
tracers/meters when no provider is installed, so the `record_*` helpers
and `span()` cost almost nothing. It turns ON when any of these is set:

    HISAAB_OTEL=1
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318   (the collector)
    OTEL_TRACES_EXPORTER=console                        (dump to stdout)

Standard OTEL_* env vars are respected (service name, resource attrs,
sampler, headers, ...). In production point OTEL_EXPORTER_OTLP_ENDPOINT at
the Cloud Trace / Cloud Monitoring OTLP receiver.

The pure core (app/core/*) never imports this module — deterministic
readiness/deadlines/chain code stays I/O-free and is instrumented from
its call sites in app/main.py instead.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Optional

from opentelemetry import metrics, trace

_ENABLED = False
_INITED = False

tracer = trace.get_tracer("hisaab")
_meter = metrics.get_meter("hisaab")

# --- instruments (no-ops until a MeterProvider is installed) ----------------
_req_inflight = _meter.create_up_down_counter(
    "hisaab.requests.inflight", description="API requests currently being handled")
_gemini_calls = _meter.create_counter(
    "hisaab.gemini.calls", description="Gemini calls by model and outcome")
_gemini_latency = _meter.create_histogram(
    "hisaab.gemini.latency", unit="ms", description="Gemini call wall time")
_gemini_tokens = _meter.create_counter(
    "hisaab.gemini.tokens", description="Gemini tokens in/out")
_gemini_cost = _meter.create_counter(
    "hisaab.gemini.cost_inr", description="Estimated Gemini spend, INR")
_readiness = _meter.create_counter(
    "hisaab.readiness.checks", description="Draft readiness verdicts by kind")
_readiness_score = _meter.create_histogram(
    "hisaab.readiness.score", description="Readiness score 0..1")
_deterministic_latency = _meter.create_histogram(
    "hisaab.deterministic.latency", unit="ms",
    description="Wall time of a pure-Python core computation")
_ratelimit_rejects = _meter.create_counter(
    "hisaab.ratelimit.rejections", description="429s from the in-memory burst limiter")
_limit_rejects = _meter.create_counter(
    "hisaab.limits.rejections",
    description="429s from the Firestore daily cap / monthly ceiling")
_evidence_uploads = _meter.create_counter(
    "hisaab.evidence.uploads", description="Evidence items added")


def init(app=None) -> bool:
    """Idempotent. Returns True if telemetry is active."""
    global _ENABLED, _INITED, tracer, _meter
    if _INITED:
        if app is not None and _ENABLED:
            _instrument_app(app)
        return _ENABLED
    _INITED = True

    if not _wanted():
        return False

    # stable HTTP semantics -> templated `http.route` on metrics, seconds unit
    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")

    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

    resource = Resource.create({
        "service.name": os.environ.get("OTEL_SERVICE_NAME", "hisaab"),
        "service.version": os.environ.get("HISAAB_VERSION", "dev"),
        "deployment.environment": os.environ.get("DEPLOY_ENV", "local"),
    })

    span_exp, metric_exp = _exporters()
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(BatchSpanProcessor(span_exp))
    trace.set_tracer_provider(tp)

    reader = PeriodicExportingMetricReader(
        metric_exp, export_interval_millis=int(os.environ.get("OTEL_METRIC_EXPORT_INTERVAL", "10000")))
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))

    tracer = trace.get_tracer("hisaab")
    _rebind_instruments()
    _ENABLED = True

    _instrument_libs()
    if app is not None:
        _instrument_app(app)
    return True


def enabled() -> bool:
    return _ENABLED


def _wanted() -> bool:
    if os.environ.get("HISAAB_OTEL", "").lower() in ("1", "true", "yes"):
        return True
    if os.environ.get("OTEL_SDK_DISABLED", "").lower() in ("1", "true"):
        return False
    return any(os.environ.get(k) for k in (
        "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "OTEL_TRACES_EXPORTER", "OTEL_METRICS_EXPORTER"))


def _exporters():
    kind = os.environ.get("OTEL_TRACES_EXPORTER", "otlp").lower()
    if kind == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter
        from opentelemetry.sdk.metrics.export import ConsoleMetricExporter
        return ConsoleSpanExporter(), ConsoleMetricExporter()
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    return OTLPSpanExporter(), OTLPMetricExporter()


def _instrument_libs():
    try:
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        RequestsInstrumentor().instrument()
    except Exception:  # noqa: BLE001
        pass


def _instrument_app(app):
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz")
    except Exception:  # noqa: BLE001
        pass


def _rebind_instruments():
    global _meter, _req_inflight, _gemini_calls, _gemini_latency, _gemini_tokens
    global _gemini_cost, _readiness, _readiness_score, _deterministic_latency
    global _ratelimit_rejects, _limit_rejects, _evidence_uploads
    _meter = metrics.get_meter("hisaab")
    _req_inflight = _meter.create_up_down_counter("hisaab.requests.inflight")
    _gemini_calls = _meter.create_counter("hisaab.gemini.calls")
    _gemini_latency = _meter.create_histogram("hisaab.gemini.latency", unit="ms")
    _gemini_tokens = _meter.create_counter("hisaab.gemini.tokens")
    _gemini_cost = _meter.create_counter("hisaab.gemini.cost_inr")
    _readiness = _meter.create_counter("hisaab.readiness.checks")
    _readiness_score = _meter.create_histogram("hisaab.readiness.score")
    _deterministic_latency = _meter.create_histogram("hisaab.deterministic.latency", unit="ms")
    _ratelimit_rejects = _meter.create_counter("hisaab.ratelimit.rejections")
    _limit_rejects = _meter.create_counter("hisaab.limits.rejections")
    _evidence_uploads = _meter.create_counter("hisaab.evidence.uploads")


# --- helpers used across the app -------------------------------------------
@contextmanager
def span(name: str, attrs: Optional[dict] = None):
    with tracer.start_as_current_span(name) as s:
        for k, v in (attrs or {}).items():
            if v is not None:
                s.set_attribute(k, v)
        yield s


@contextmanager
def measure(name: str, attrs: Optional[dict] = None):
    """Time a pure deterministic computation and record it as a metric + span."""
    import time
    t0 = time.perf_counter()
    with span("core." + name, attrs):
        try:
            yield
        finally:
            _deterministic_latency.record(
                (time.perf_counter() - t0) * 1000, {"op": name})


def record_gemini(*, model: str, ok: bool, latency_ms: int, in_tokens: int,
                  out_tokens: int, cost_inr: float, fell_back: bool) -> None:
    common = {"model": model, "ok": ok, "fell_back": fell_back}
    _gemini_calls.add(1, common)
    _gemini_latency.record(latency_ms, {"model": model, "ok": ok})
    if in_tokens:
        _gemini_tokens.add(in_tokens, {"model": model, "direction": "in"})
    if out_tokens:
        _gemini_tokens.add(out_tokens, {"model": model, "direction": "out"})
    if cost_inr:
        _gemini_cost.add(cost_inr, {"model": model})


def record_readiness(kind: str, ready: bool, score: float) -> None:
    _readiness.add(1, {"kind": kind, "ready": ready})
    _readiness_score.record(score, {"kind": kind})


def record_ratelimit_reject(bucket: str, window: str) -> None:
    _ratelimit_rejects.add(1, {"bucket": bucket, "window": window})


def record_limit_reject(reason: str) -> None:
    _limit_rejects.add(1, {"reason": reason})


def record_evidence(kind: str, degraded: bool) -> None:
    _evidence_uploads.add(1, {"kind": kind, "degraded": degraded})


@contextmanager
def inflight():
    _req_inflight.add(1)
    try:
        yield
    finally:
        _req_inflight.add(-1)

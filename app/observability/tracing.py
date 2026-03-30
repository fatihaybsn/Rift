"""OpenTelemetry tracing bootstrap and FastAPI instrumentation."""

from __future__ import annotations

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

_INSTRUMENTED_APPS: set[int] = set()
_TRACING_CONFIGURED = False


def configure_tracing(
    *,
    service_name: str,
    environment: str,
    exporter_mode: str,
    otlp_endpoint: str | None,
) -> None:
    """Configure global OpenTelemetry provider once per process."""
    global _TRACING_CONFIGURED
    if _TRACING_CONFIGURED:
        return

    resource = Resource.create(
        {
            "service.name": service_name,
            "deployment.environment": environment,
        }
    )
    provider = TracerProvider(resource=resource)

    mode = exporter_mode.lower().strip()
    if mode == "console":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    elif mode == "otlp":
        exporter_kwargs: dict[str, str] = {}
        if otlp_endpoint:
            exporter_kwargs["endpoint"] = otlp_endpoint
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(**exporter_kwargs)))

    trace.set_tracer_provider(provider)
    _TRACING_CONFIGURED = True


def instrument_fastapi(app: FastAPI) -> None:
    """Enable FastAPI request tracing once per app instance."""
    app_key = id(app)
    if app_key in _INSTRUMENTED_APPS:
        return
    FastAPIInstrumentor.instrument_app(app)
    _INSTRUMENTED_APPS.add(app_key)


def get_tracer(name: str):
    """Return named tracer bound to current provider."""
    return trace.get_tracer(name)


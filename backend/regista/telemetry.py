"""OpenTelemetry for the warm path: one trace per rendering, exported over OTLP when an endpoint is configured.

Agent Framework already traces its own work (agent runs, model calls, tool executions, GenAI semantic conventions).
Regista adds the spans it cannot see: the rendering for one viewer, each Narrator draft, each Verifier verdict with
its notes, and the template fallback, so a trace answers "why did this graphic air, and how long did it take".

Nothing is exported unless asked: set ``OTEL_EXPORTER_OTLP_ENDPOINT`` (e.g. http://localhost:4317 for a local Aspire
dashboard or Jaeger) or ``ENABLE_CONSOLE_EXPORTERS=true``. Without them the tracer is the OpenTelemetry no-op.
The hot path is not traced: a span per event would cost more than the event itself (about 27 µs).
"""

from __future__ import annotations

import os

from opentelemetry import trace

tracer = trace.get_tracer("regista")

_configured = False


def tracing_requested() -> bool:
    """True when the environment asks for traces to be exported."""
    keys = ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    return any(os.getenv(k) for k in keys) or os.getenv("ENABLE_CONSOLE_EXPORTERS", "").lower() == "true"


def setup_tracing(service_name: str = "regista") -> bool:
    """Configure exporters once, through Agent Framework so its spans and Regista's share one provider.

    Returns True when tracing is on. Needs the ``tracing`` extra (opentelemetry-sdk and the OTLP exporter).
    """
    global _configured
    if _configured or not tracing_requested():
        return _configured
    from agent_framework.observability import configure_otel_providers

    configure_otel_providers(service_name=os.getenv("OTEL_SERVICE_NAME", service_name))
    _configured = True
    return True

"""Warm-path traces: one span tree per rendering, with the Verifier's verdicts, nested with Agent Framework's spans."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402
from test_agents_orchestrator import Narration, client_for, first, seed7  # noqa: E402, F401

from regista.agents.orchestrator import WarmPath  # noqa: E402
from regista.agents.profiles import PRESETS  # noqa: E402
from regista.telemetry import setup_tracing, tracing_requested  # noqa: E402


@pytest.fixture(scope="module")
def spans():
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):  # the global provider can be set once per process
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


def test_a_revised_render_is_one_span_tree(seed7, spans, monkeypatch):  # noqa: F811
    monkeypatch.delenv("REGISTA_LLM_LANGUAGES", raising=False)
    match, insights, contexts = seed7
    press = first(insights, "press_change")
    spans.clear()
    warm = WarmPath(match.meta, client_for(Narration(wrong_first=True)))
    result = asyncio.run(warm.render(contexts[press.insight_id], PRESETS["analyst-en"]))
    assert result.source == "llm_revised"

    got = spans.get_finished_spans()
    by_name: dict[str, list] = {}
    for s in got:
        by_name.setdefault(s.name, []).append(s)
    render = by_name["regista.render"][0]
    assert render.attributes["regista.insight_id"] == press.insight_id
    assert render.attributes["regista.profile_id"] == "analyst-en"
    assert render.attributes["regista.source"] == "llm_revised"
    assert render.attributes["regista.drafts"] == 2 and render.attributes["regista.rejections"] == 1

    checks = sorted(by_name["regista.verifier.check"], key=lambda s: s.attributes["regista.attempt"])
    assert [c.attributes["regista.status"] for c in checks] == ["rejected", "ok"]
    assert any("does not match" in n for n in checks[0].attributes["regista.notes"])
    assert len(by_name["regista.narrator.draft"]) == 2
    brief = by_name["regista.analyst.brief"][0]
    assert brief.attributes["regista.source"] == "llm" and brief.attributes["regista.tool_calls"] == 2

    # Everything belongs to the render's trace, Agent Framework's own agent and tool spans included.
    assert {s.context.trace_id for s in got} == {render.context.trace_id}
    ours = {"regista.render", "regista.verifier.check", "regista.narrator.draft", "regista.analyst.brief"}
    framework = [s.name for s in got if s.name not in ours]
    assert any("Analyst" in n for n in framework) and any("get_facts" in n for n in framework), framework


def test_a_template_render_traces_the_fallback(seed7, spans):  # noqa: F811
    match, insights, contexts = seed7
    goal = first(insights, "goal")
    spans.clear()
    asyncio.run(WarmPath(match.meta, None).render(contexts[goal.insight_id], PRESETS["casual-es-slm"]))
    names = [s.name for s in spans.get_finished_spans()]
    assert names.count("regista.template.render") == 1 and "regista.narrator.draft" not in names
    render = next(s for s in spans.get_finished_spans() if s.name == "regista.render")
    assert render.attributes["regista.source"] == "template" and render.attributes["regista.language"] == "es"


def test_export_is_off_unless_asked(monkeypatch):
    for k in ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "ENABLE_CONSOLE_EXPORTERS"):
        monkeypatch.delenv(k, raising=False)
    assert not tracing_requested() and setup_tracing() is False
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    assert tracing_requested()

# Decisions

Short records of non-obvious choices. Add new ones at the bottom.

## D1. Two tiers: deterministic hot path, agentic warm path

LLMs never run per event. Metrics and detectors are pure code (testable, under 200 ms, no hallucination risk, no per-event cost).
Agents run only on detected moments and on schedule (half time, full time recap), with a 1.5 to 3 s budget. Broadcast graphics
already lag live action and narratives land around stoppages, so this latency is acceptable.

## D2. Facts with evidence are the unit of truth

Detectors emit an `Insight` with `facts[]`, each carrying `evidence[]` (event ids or metric keys plus a time window). Every rendered
sentence (`Claim`) lists the `fact_ids` it relies on. This makes verification mechanical and keeps facts identical across
languages and modes. It is the core explainability and anti-hallucination story.

## D3. Three agents: Analyst, Narrator, Verifier

- Analyst: tool access to match state; selects and frames facts; never invents numbers.
- Narrator: renders one `RenderedInsight` per `FanProfile` (mode, language, club, player focus).
- Verifier: checks each claim's numbers and entities against the cited facts; rejects with reasons; Narrator retries once,
  then falls back to a deterministic template. A rejected-then-fixed example should appear in the demo trace view.
Stretch: expose match state as an MCP server so the Analyst's tools are reusable.

## D4. Generate in the target language from facts, do not translate prose

Translation of finished prose drifts numbers and names. Narrator writes directly in the target language from the canonical
facts; the Verifier checks numbers in every language.

## D5. Simulator: possession-chain model with continuous positions

Pressure, pass difficulty and shot quality emerge from player geometry rather than being sampled directly, so the analytics
layer has something real to measure. One seeded RNG for determinism.

## D6. Planted storylines plus ground truth

The director overrides team parameters in time windows (control, chaos, high press, go long) and scripts four moments
(three goals, one record sprint). Organic shots never score, so the scoreline is fixed for the demo while chance quality stays
realistic. `*.truth.json` records storylines, scripted event ids, true xG per shot and model coefficients, used only for
evaluation and tests.

## D7. Clock fields

`match_clock_s` is the broadcast clock and restarts at 2700 for period 2, so it overlaps first-half stoppage. Added
`elapsed_s` (monotonic) for replay ordering and time-series metrics, and `match_minute()` for minute windows.

## D8. Contracts: Pydantic is the source of truth

Pydantic -> JSON Schema (`backend/scripts/export_schemas.py`) -> TypeScript (`frontend/scripts/gen-contracts.mjs`).
Property titles are stripped for clean TS; serialization-mode schemas make defaulted fields (like the `type` discriminator)
required. CI fails on drift.

## D9. Minimal infra

FastAPI WebSocket instead of Event Hubs and SignalR; in-memory state instead of Cosmos DB. Deploy backend and frontend to
Azure Container Apps with `azd up`. Observability via OpenTelemetry to Application Insights. Event Hubs is mentioned in the
README as the production ingest swap.

## D10. Fictional universe

No real clubs, players, competitions, crests or music (hackathon data rule and video trademark rule).

## D11. Foundry client first

`FoundryChatClient` against a Foundry project endpoint is the primary path (hero technology, evals available). Plain Azure
OpenAI via `OpenAIChatClient` is the fallback when only an AOAI resource exists.

## D12. Provider-agnostic LLM layer

No Azure subscription at build start. `regista/llm.py` selects foundry, azure_openai, foundry_local, openai_compat or none
from env. Build and test against a local model or templates; switch to Foundry for the recorded demo and deployment, which
the rubric (hero technologies, runs on Azure) needs. Agents must degrade to deterministic templates when the client is None.

# CLAUDE.md

Context for Claude Code working in this repo. Read this first, then `docs/PLAN.md` for what to do next.

## What this is

**Regista** is a solo entry for *Inside the Game: Developer Hackathon* (Microsoft x Premier League, Innovation Studio).
It turns a stream of synthetic football events into explained, verified, personalized match intelligence for broadcast and streaming.

- Submission deadline: **27 Oct 2026, 11:59 PM PT** (= 28 Oct, 12:29 PM IST). Treat **27 Oct IST night** as the real deadline.
- Owner: Satish Jhanwer (solo). Frontend architect and AI/ML practitioner. Treat him as a technical peer.
- Brief, rubric and submission rules: `docs/HACKATHON.md`. Architecture decisions: `docs/DECISIONS.md`. Day plan and status: `docs/PLAN.md`. Pitch copy: `docs/SUBMISSION.md`.

## Architecture in one paragraph

A seeded simulator produces a match (`data/RGS-2026-0001.json`). A replay service streams events. The **hot path** is
deterministic: a match state engine computes metrics (pass difficulty, xG, momentum, control vs chaos, press change)
and moment detectors emit a canonical `Insight` carrying `facts` with `evidence` refs. No LLM on the hot path, budget under 200 ms.
The **warm path** runs only on detected moments: Microsoft Agent Framework agents on a Microsoft Foundry model.
Analyst (tools over match state, never invents numbers), Narrator (renders per `FanProfile`), Verifier (every sentence's
`fact_ids` must resolve and match; reject and retry otherwise). Output is an `OverlayPayload` pushed over WebSocket to a
React + TypeScript overlay with fan controls (mode, club, player focus, language). Runs locally; FastAPI serves the built
frontend as one service. No Azure deployment (no subscription).

## Repo layout

```text
backend/regista/contracts/  Pydantic contracts. SINGLE SOURCE OF TRUTH for events, Insight, OverlayPayload, FanProfile
backend/regista/sim/        Simulator: roster.py (fictional teams), director.py (storylines + script), engine.py, __main__.py (CLI)
backend/regista/state/      Hot-path metrics: core.py (MatchState, rolling windows), models.py (+ models/*.json), momentum.py,
                            control.py, press.py (gated CUSUM), records.py (speeds, milestones). build_state(meta) wires all
backend/regista/detect/     detectors.py (9 kinds), pipeline.py (InsightPipeline, cooldown/dedupe, run_match), __main__.py (CLI)
backend/regista/agents/     verifier.py (code gate), templates.py + phrases.py (en/es/hi fallback), profiles.py (presets,
                            relevance, slots), context.py (snapshot + Analyst tools), analyst.py, narrator.py,
                            orchestrator.py (WarmPath: verify/retry/fallback, cache, traces), recap.py, __main__.py (record)
backend/regista/api/        replay.py (deterministic Replay), hub.py (shared clock, fan-out), app.py (FastAPI + /ws). docs/API.md
backend/scripts/            export_schemas.py (Pydantic -> JSON Schema), hello_foundry.py (agent smoke test), fit_models.py
backend/tests/              simulator, contracts, state/models/momentum/control/press/records, test_detect.py (acceptance)
contracts/schema/           Exported JSON Schemas (generated, committed)
frontend/src/contracts/     TS types generated from contracts/schema (generated, committed, never hand-edit)
frontend/src/lib/           overlayQueue.ts (slot scheduler), live.ts (stream reducer), api.ts (REST + useLiveStream)
frontend/src/components/    Pitch, Overlays (graphics slots), Metrics (ribbon, chaos), Controls, Trace, Compare
data/                       Canonical demo match (seed 7) + truth file
```

Planned (not yet built): `infra/` Bicep + `azure.yaml`.

## Commands

```bash
cd backend
pip install -e ".[dev,agents,api]"
pytest -q                                   # must stay green
ruff check . && ruff format .               # line length 140
python -m regista.sim generate --seed 7 --out ../data
python -m regista.sim summary ../data/RGS-2026-0001.json
python -m regista.detect ../data/RGS-2026-0001.json   # insight timeline + per-event latency
python -m regista.api                       # replay API on :8000 (see docs/API.md)
npm run dev --prefix ../frontend           # overlay app on :5173; npm test / typecheck / build likewise
python -m regista.agents record ../data/RGS-2026-0001.json --out ../data/RGS-2026-0001.renders.json   # add --resume to re-audit
REGISTA_LLM_PROVIDER=none REGISTA_AGENT_CACHE=../data/RGS-2026-0001.renders.foundry-local.json python -m regista.api   # demo mode
python scripts/eval_run.py ../data/RGS-2026-0001.renders.foundry-local.json --markdown   # recorded-run eval
python scripts/fit_models.py                # refit pass/xG models on seeds 1-5, report vs truth on seed 7
python scripts/hello_foundry.py             # needs .env (see .env.example) + az login

# after changing any contract model:
python scripts/export_schemas.py
npm install --prefix ../frontend && npm run contracts --prefix ../frontend
```

CI (`.github/workflows/ci.yml`) runs ruff, pytest, and fails if generated schemas/TS types are stale.

## Conventions and invariants (do not break)

- **Contracts flow one way:** Pydantic -> JSON Schema -> TypeScript. Change Python, regenerate, commit all three.
- **Coordinates:** absolute metres, x in [0,105], y in [0,68]. Direction depends on period: use `attacks_right(meta, team_id, period)`.
  Convert to the team's attacking frame before computing xG, thirds, progressive passes.
- **Clocks:** `t` = seconds into period (stoppage included). `match_clock_s` = broadcast clock, restarts at 2700 in period 2, so
  NOT monotonic. `elapsed_s` = monotonic, use for replay ordering and EWMA/CUSUM. Use `match_minute(period, t)` for
  minute windows (stoppage folds into 44.99 / 89.99). Display with `format_clock(period, t)`.
- **Ground truth isolation:** `*.truth.json` is for evaluation and tests only. Never load it in the pipeline, agents or UI.
- **Facts before prose:** every number on screen must come from a `Fact`. Agents get tools and facts; they never compute.
- **Fictional only:** no real clubs, players, competitions, crests, or league data anywhere (hackathon rule + trademark rule for the video).
  Teams: Northvale FC (`NVL`, home) vs Saltmere Athletic (`SLM`). Venue: Harbourline Park.
- **Secrets:** `.env` is gitignored. Prefer Entra ID (`DefaultAzureCredential`) over API keys.
- **Determinism:** simulator uses one seeded `random.Random`. Same seed must produce byte-identical output (tested).
- **Documentation:** every public module, class, function and method has a docstring (ruff `D1`, enforced in CI);
  exported TypeScript gets TSDoc. Comments explain *why*, never restate the code. No commented-out code.

## LLM access (important)

The owner has **no Azure subscription** (and will not for this submission). All agent code must get its client from `regista.llm.build_chat_client()`,
never construct a client directly. Providers: `foundry` (submission target), `azure_openai`, `foundry_local`,
`openai_compat` (Ollama etc.), `none` (deterministic templates). Every agent path must work with `none` so tests, CI and
an offline demo never need a model. The demo model runs on Microsoft Foundry Local (`foundry_local`, CPU variant of
qwen2.5-3b; `llm.foundry_local_endpoint` works around agent-framework-foundry-local pinning an SDK older than the
current Foundry Local CLI).

## Agent Framework notes (verified 23 Oct 2026, agent-framework-core 1.22)

- Packages are split: `agent-framework-core`, `agent-framework-foundry`, `agent-framework-openai`. All pinned in `pyproject.toml` extra `agents`.
- `from agent_framework import Agent`; `Agent(client=..., name=..., instructions=..., tools=[fn, ...])`; `await agent.run(text)`.
- Foundry: `from agent_framework.foundry import FoundryChatClient`; `FoundryChatClient(project_endpoint=..., model=..., credential=DefaultAzureCredential())`.
  Env vars `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_MODEL`. Uses the Responses API.
- `agent_framework.foundry` also exposes `FoundryEvals` / `evaluate_traces` (groundedness eval for the Verifier story).
- Function tools: plain functions with `Annotated[type, Field(description=...)]` params and a docstring.
- Tests drive the real Agent loop with `tests/fake_llm.py` (`ScriptedClient`: FunctionInvocationLayer + BaseChatClient).
- The API moves fast. If something does not match, inspect signatures (`inspect.signature`) before guessing.

## Simulator facts the next stages rely on

Demo match seed 7: **Northvale 2-1 Saltmere**. Scripted ids are in the truth file under `scripted_event_ids` (G1, G2, M1, G3).

| When | Storyline / moment | What detectors should find |
| --- | --- | --- |
| 0-25' | S1 Northvale control | high NVL completion, long sequences, low sequence entropy |
| 25-40' | S2 chaos spell | turnovers/min up about 1.5-2x, long-ball share up, short sequences |
| 38' | G1 Nordgren through ball, Vukovic goal (NVL-09) | key pass (through ball), shot quality |
| 58-72' | S3 Saltmere high press | SLM pressures per NVL pass about 2-4x baseline, NVL completion down |
| 64' | G2 Lindqvist (SLM-06) tackle high, Shapira (SLM-09) goal | press -> turnover -> goal chain |
| 76' | M1 Balogun (SLM-11) sprint 34.8 km/h | fastest sprint of the match, player tag |
| 72-96' | S4 Northvale go long | NVL long-ball share up, SLM press fades |
| 88' | G3 Haddad (NVL-07) cross, Vukovic header | brace milestone (career goals are in roster) |

Pass model and xG model coefficients are in the truth file, so the metrics layer can be evaluated (calibration, Brier score)
against `xg_true` without peeking at it at runtime.

## Working style for this repo

- Ship over polish: 5-day solo build. Prefer the simplest thing that scores on the rubric (see `docs/HACKATHON.md`).
- Keep the deterministic layer tested. Every new metric/detector gets a test against the planted storylines.
- Update `docs/PLAN.md` status checkboxes when a stage lands. Record non-obvious choices in `docs/DECISIONS.md`.
- Before submission the repo must be **public** with an MIT license (already present).

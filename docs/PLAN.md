# Build plan and status

Solo, about 5 days around a day job. Deadline: submit by **Tue 27 Oct night IST** (hard cutoff 28 Oct 12:29 PM IST).
Update the checkboxes as stages land.

## Thu 22 Oct: scaffold (done)

- [x] Repo layout, pyproject, ruff, pytest, CI, MIT license, .gitignore, .env.example
- [x] Event + overlay contracts (Pydantic), JSON Schema export, generated TS types, drift test
- [x] Simulator with planted storylines, ground-truth file, CLI summary, demo match seed 7
- [x] `hello_foundry.py` smoke test (Agent Framework + FoundryChatClient, one tool)
- [x] Provider-agnostic LLM factory (`regista/llm.py`): foundry, azure_openai, foundry_local, openai_compat, none
- [ ] Get Azure access (free account) and run `hello_foundry.py` against Foundry; meanwhile run it on a local model

## Fri 23 Oct: match state engine + detectors (done)

Package `backend/regista/state/` and `backend/regista/detect/`.

- [x] `MatchState.apply(event)` incremental, O(1) per event, keyed by `elapsed_s`
- [x] Pass difficulty: own logistic `P(complete | length, passer pressure, receiver pressure, height)`, difficulty = 1 - P.
      Fit on seeds other than 7, report calibration vs truth coefficients.
- [x] xG: logistic on distance, angle, header, defenders within 5 m. Report Brier score vs `xg_true`.
- [x] Momentum: EWMA of territorial/threat delta per team (half-life 3 to 5 min, on `elapsed_s`)
- [x] Control vs chaos: rolling turnover rate + mean sequence length + Shannon entropy of possession transitions
- [x] Press intensity: opponent pressures per pass (PPDA-like) in rolling window; CUSUM change-point for press shifts
- [x] Speed/threshold tagging: sprint >= 30 km/h, shot speed, pass ball speed, match-max records
- [x] Milestones: brace/hat-trick, career goal/appearance landmarks from roster
- [x] Detectors emit `Insight` with facts + evidence; dedupe and cooldown per kind
- [x] Tests: each storyline S1-S4 and moments G1-G3, M1 detected within its window on seeds 1-5, 7; no false press-shift in 0-55'
      Press: all six acceptance seeds pass; on 40 seeds the gated CUSUM has 2 false SLM alarms before 55' and 2 misses
      in 58-66' (see D18). S4 is covered at metric level (long-ball share), no dedicated detector. Replay: `python -m regista.detect ../data/RGS-2026-0001.json` (p95 ~50 us per event).

## Sat 24 Oct: agents + API (done, pending a real model run)

Package `backend/regista/agents/` and `backend/regista/api/`.

- [x] Analyst (tools: get_state, get_facts, get_player, get_window_stats), Narrator, Verifier on Agent Framework + Foundry
      Built on Agent Framework and tested through its real tool loop with a scripted chat client. Not yet run against
      Foundry or any live model (no Azure access or local model on this machine yet).
- [x] Verifier: numeric/entity check of each `Claim` against cited facts; retry once; template fallback
- [x] Recap at half time and full time from accumulated insights
- [x] FastAPI: replay service (speed x10/x20, pause, seek), WebSocket `/ws?profile=...` streaming `OverlayPayload`
- [x] Per-profile fan-out: one Insight -> N RenderedInsights (cache by insight_id + profile)
- [x] Record a cached agent-output run for deterministic demo recording (`python -m regista.agents record`)
- [x] First live-model runs (Ollama, qwen2.5:3b on CPU): real Verifier rejections and revisions, rules hardened (D28)
- [x] Demo cache recorded with qwen2.5:3b: `data/RGS-2026-0001.renders.json` (serve with REGISTA_AGENT_CACHE)
- [ ] Re-record with Foundry once Azure is available (`record --resume` keeps what still verifies)

## Sun 25 Oct: frontend (done, built Fri ahead of the model run)

Vite + React + TypeScript in `frontend/`, types from `src/contracts` (incl. the generated stream protocol).

- [x] Pitch view with live events, broadcast clock, score bug
- [x] Overlay slots: lower third, top bar, player tag, ticker; TTL + priority queue keyed to match clock
      (side panel too; air clock pauses with the replay; scheduler unit-tested)
- [x] Momentum ribbon, control vs chaos meter (ribbon backfills from `/api/momentum` on join and seek)
- [x] Fan control panel: mode (analyst/casual/player focus), favorite club, focus player, language (en + hi + es)
- [x] Side-by-side compare view (same moment, two profiles) for the demo
- [x] Agent trace panel: Analyst -> Narrator -> Verifier, claims mapped to facts and evidence
- [x] Trace showing a real rejected claim (recorded run: e.g. 64' goal, Spanish casual: attribution reject, then revised)

## Mon 26 Oct: ship and harden

- [ ] Azure access confirmed no later than Sunday night, otherwise ship with local model + templates and say so in README
- [ ] `azure.yaml` + Bicep: Container Apps (api, web), managed identity to Foundry, Log Analytics + App Insights
- [ ] `azd up` works from clean clone
- [ ] OpenTelemetry traces of agent runs
- [ ] Groundedness eval script (Foundry evals) over recorded run; report number in README
- [ ] README: architecture diagram, latency table, eval results, setup

## Tue 27 Oct: video + submit

- [ ] 2-minute video (script in `docs/SUBMISSION.md`), no copyrighted music, fictional names only, upload to YouTube
- [ ] Make repo **public**
- [ ] Project page: description, video URL, repo URL, cover image (architecture diagram + overlay frame)
- [ ] Submit by Tuesday night IST

## Stretch (only if ahead)

- MCP server over match state (FastMCP), Analyst consumes it
- Third language
- Event Hubs ingest path

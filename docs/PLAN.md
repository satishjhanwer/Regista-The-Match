# Build plan and status

Solo, about 5 days around a day job. Deadline: submit by **Tue 27 Oct night IST** (hard cutoff 28 Oct 12:29 PM IST).
Update the checkboxes as stages land.

## Thu 22 Oct: scaffold (done)
- [x] Repo layout, pyproject, ruff, pytest, CI, MIT license, .gitignore, .env.example
- [x] Event + overlay contracts (Pydantic), JSON Schema export, generated TS types, drift test
- [x] Simulator with planted storylines, ground-truth file, CLI summary, demo match seed 7
- [x] `hello_foundry.py` smoke test (Agent Framework + FoundryChatClient, one tool)
- [ ] **Run `hello_foundry.py` against a real Foundry deployment** (needs Azure; check model quota in region)

## Fri 23 Oct: match state engine + detectors
Package `backend/regista/state/` and `backend/regista/detect/`.
- [ ] `MatchState.apply(event)` incremental, O(1) per event, keyed by `elapsed_s`
- [ ] Pass difficulty: own logistic `P(complete | length, passer pressure, receiver pressure, height)`, difficulty = 1 - P.
      Fit on seeds other than 7, report calibration vs truth coefficients.
- [ ] xG: logistic on distance, angle, header, defenders within 5 m. Report Brier score vs `xg_true`.
- [ ] Momentum: EWMA of territorial/threat delta per team (half-life 3 to 5 min, on `elapsed_s`)
- [ ] Control vs chaos: rolling turnover rate + mean sequence length + Shannon entropy of possession transitions
- [ ] Press intensity: opponent pressures per pass (PPDA-like) in rolling window; CUSUM change-point for press shifts
- [ ] Speed/threshold tagging: sprint >= 30 km/h, shot speed, pass ball speed, match-max records
- [ ] Milestones: brace/hat-trick, career goal/appearance landmarks from roster
- [ ] Detectors emit `Insight` with facts + evidence; dedupe and cooldown per kind
- [ ] Tests: each storyline S1-S4 and moments G1-G3, M1 detected within its window on seeds 1-5, 7; no false press-shift in 0-55'

## Sat 24 Oct: agents + API
Package `backend/regista/agents/` and `backend/regista/api/`.
- [ ] Analyst (tools: get_state, get_facts, get_player, get_window_stats), Narrator, Verifier on Agent Framework + Foundry
- [ ] Verifier: numeric/entity check of each `Claim` against cited facts; retry once; template fallback
- [ ] Recap at half time and full time from accumulated insights
- [ ] FastAPI: replay service (speed x10/x20, pause, seek), WebSocket `/ws?profile=...` streaming `OverlayPayload`
- [ ] Per-profile fan-out: one Insight -> N RenderedInsights (cache by insight_id + profile)
- [ ] Record a cached agent-output run for deterministic demo recording

## Sun 25 Oct: frontend
Vite + React + TypeScript in `frontend/`, types from `src/contracts`.
- [ ] Pitch view with live events, broadcast clock, score bug
- [ ] Overlay slots: lower third, top bar, player tag, ticker; TTL + priority queue keyed to match clock
- [ ] Momentum ribbon, control vs chaos meter
- [ ] Fan control panel: mode (analyst/casual/player focus), favorite club, focus player, language (en + hi or es)
- [ ] Side-by-side compare view (same moment, two profiles) for the demo
- [ ] Agent trace panel: Analyst -> Narrator -> Verifier, showing a rejected claim

## Mon 26 Oct: ship and harden
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

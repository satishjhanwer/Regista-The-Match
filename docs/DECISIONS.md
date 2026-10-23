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

## D13. State engine: one incremental object, pluggable components

`MatchState.apply(event)` updates core counters (per-team rolling 5 and 10 minute sums plus match totals), then runs
components in a fixed order: pass difficulty, xG, momentum, control vs chaos, press, records. It returns `MetricUpdate`s
whose window bounds (in `elapsed_s`) double as `EvidenceRef` windows. Events must arrive in non-decreasing `elapsed_s`
(out-of-order raises). Rolling windows run across half-time, because `elapsed_s` has no break gap. Momentum and the press
CUSUM reset per half on purpose. About 25 us per event in pure Python, no numpy needed.

## D14. Pass difficulty model

Logistic on length, passer and receiver defenders within 5 m, and high-ball flag, fitted by Newton-Raphson on seeds 1-5
(5,941 passes). The slopes land near the simulator's truth (length -0.087 vs -0.075, receiver pressure -0.36 vs -0.35,
high -0.64 vs -0.60). The intercept (4.22 vs 3.60) absorbs the per-team pass-skill offset that the features cannot see,
and passer pressure (-0.74 vs -0.55) also absorbs the chaos spell, where pressure and low skill coincide. Seed 7 Brier:
0.129 vs 0.165 for the constant training rate. 5-bin calibration is within 0.03 in every bin.
`python scripts/fit_models.py` refits and prints all of this.

## D15. xG fitted on soft labels

Organic shots never score (D6), so binary outcomes carry no signal: 3 goals per match, all scripted. The fit script uses
`xg_true` as soft labels (cross-entropy). The truth file is read by the script only, never at runtime. Because `xg_true`
is a noiseless logistic of the same four features, this recovers the truth coefficients exactly, so seed 7 calibration
matches by construction. Expected Brier on seed 7: 0.136 vs 0.163 for mean xG. As an honest robustness check, the script
also fits on Bernoulli(`xg_true`) outcomes (seeded, 22 goals in 150 shots): 0.142, still better than baseline.

## D16. Momentum signal

Impulse EWMA per team, half-life 4 minutes on `elapsed_s`, reset at each period start. Weights: completed pass ending in
the attacking final third 1.0, carry ending there 0.5, shot 10 x xG. The index is (H - A) / (H + A). Both teams decay at
the same rate, so the index only changes when someone adds threat. The detector fires when a different team becomes
dominant (|index| >= 0.4, released below 0.1). It waits 6 minutes into a half and needs a minimum activity level, so the
half-time reset does not produce "100% momentum" noise.

## D17. Control vs chaos weights

Chaos = 0.4 x turnover rate (open-play turnovers per team per minute, / 2.0, clipped) + 0.3 x sequence shortness
(1 - (passes per possession - 1) / 7, clipped) + 0.3 x conditional Shannon entropy (bits) of "does the next on-ball
action stay with this team". Team control = 1 - chaos on the team's own possessions. Scales come from observed ranges:
S1 about 0.4 match chaos, S2 about 0.87. Regimes have hysteresis (chaos at >= 0.70, held >= 0.60; control at <= 0.45,
held <= 0.55). "Control" also needs a dominant side: control >= 0.6, 0.1 above the opponent, and >= 55% of the passes.
Without that, a calm game flip-flops between "X in control" and "Y in control".

## D18. Press change: gated CUSUM on the pressed-pass indicator

Reported metric, as planned: pressing team's pressure events per opponent pass (PPDA-like) over 5 and 10 minutes,
plus the share of opponent passes made with a defender within 5 m.

Change-point design, and why it differs from the plan:

- **The S2 confound is real.** During the chaos spell both teams press at 0.65, while SLM sit off at 0.25 in S1. With a
  first-half baseline from S1, SLM's pressure per pass rises about 3x in S2, the same relative jump as S3. Every
  ungated CUSUM variant false-alarmed in 25-40' on 7-10 of 12 seeds. Only the absolute size of the shift separates
  them (S2 about +0.3, S3 about +0.6 pressures per pass).
- **Stability gate.** A press change means a team presses harder while keeping its own game. In S2, SLM's own
  completion collapses (about 0.5 vs 0.8); in S3 it does not. The CUSUM resets while the presser's completion is
  below its baseline (last 3 min by 0.12, or its last 5 passes by 0.25). That rise is reported by control vs chaos.
- **CUSUM input.** The input is the per-pass indicator "passer had a defender within 5 m", not raw pressure counts.
  Pressure events are bursty (several per possession), and the count CUSUM was much noisier for the same delay.
- **Baseline and confirmation.** k = 0.25 is set from the minimum shift worth reporting, not from noise; h = 2.5.
  The baseline is the first 20 minutes of each half, in-control samples only, and the CUSUM arms after 5 minutes.
  S3 starts 13 minutes into the second half, so waiting for the full 20-minute baseline would detect too late.
  An alarm also needs the 3-minute pressed share to exceed baseline + 0.25; until then S is held.
- **One insight per press spell.** The detector re-arms only when the pressed share falls back near baseline.

Measured on 40 seeds: SLM false alarm before 55' on 2, miss of 58-66' on 2. Seeds 1-5 and 7 are clean. On held-out
seeds 8-25 (end-to-end), 15/18 pass every acceptance criterion; all three failures are press timing (one at 66.9').
Remaining false alarms are noise during the first-half baseline window.

## D19. Detector conventions

- Insight ids are `<match>-INS-<n>`. Fact ids are `<insight>-F<n>`. `created_at` = kickoff + `elapsed_s`, so replays
  are byte-identical.
- Cooldowns apply per (kind, scope); scope is team, player or match. Dedupe keys come from the triggering event or
  regime. Detectors with regimes (momentum, control vs chaos, press) learn through the `admitted` hook whether the
  pipeline accepted a draft.
- Numbers are rounded once, in the fact, so renderings and the Verifier see the same value. Shares are integer percent.
- Speed records are announced only after 10 minutes and above a floor (sprint 30, shot 100, pass 70 km/h). Milestones
  use roster career totals before the match plus match events. Evidence is goal event ids plus a
  `<player>.career_goals_before_match` metric ref.
- Long ball = non-cross pass over 32 m, or lofted non-cross pass over 25 m. The simulator's long balls often land at
  25-32 m, and length alone missed S4 on seed 7.
- G2's press -> turnover -> goal chain is built from the possession that produced the goal: who won it, seconds to goal,
  distance from goal, and the pressed share if the scoring team has an active press alarm.

## D20. The Verifier is code, not a model

The gate that keeps ungrounded claims off screen must not be able to hallucinate. `agents/verifier.py` checks each
claim mechanically. Cited fact ids must exist. Every number must equal a cited fact's value, previous value, a number
inside a string value (score, clock) or label (window length), its 0-1 value as a percentage, or the moment's clock.
Fan-colour claims with no citation may contain no numbers. Players named must be entities of the insight or cited
values. Numbers are read after normalizing Devanagari digits and decimal commas, so the check is the same in en/es/hi.
Its feedback text goes back to the Narrator for the single retry. Limit: numbers written as words ("two") are not
caught. Prompts ask for digits.

## D21. Analyst tools read a frozen snapshot and mint candidate facts

The warm path runs after the hot path has moved on, so `capture(state, insight)` freezes what the Analyst may see
when the insight fires (window stats for both teams and windows, player totals, score, momentum, chaos). Tools never
compute. Every number a tool returns is registered as a candidate fact with metric evidence. Only candidates the
Analyst selects are appended to the insight, so the Narrator can cite them and the Verifier can check them. A number
that never became a fact cannot reach the screen. The rule-based Analyst (no model) selects the detector's facts.

## D22. Narration output is structured, and code formats the numbers it can

The Narrator returns JSON with a headline, claims with `fact_ids`, and a stat callout fact id. The body is the claims
joined (the Verifier enforces this). The stat callout value is formatted from the fact by code. Template narration is
the fallback, built from per-kind phrase specs in `agents/phrases.py`, written per language rather than translated.
A test renders every insight on six seeds for 14 profiles and requires all of them to verify. On a second rejection,
an error or a 20 s timeout, the template is used and the trace records why.

## D23. One shared replay clock, renders cached per (insight, profile)

The API models a studio feed: one replay clock (speed, pause, seek, step), many viewers. Each tick pushes clock and
metrics, raw events and overlays to every viewer. An insight is dispatched to a viewer only if `relevance()` keeps it
for that profile, and only verified or revised renders are sent. The Analyst runs once per insight and each
(insight, profile) renders once (single-flight), so N viewers with the same profile cost one model call. Seeking
backwards rebuilds the hot path (under 100 ms). Insight ids are deterministic, so the cache survives seeks.
Moments skipped by a seek go to history, not to screens.

## D24. Recorded runs for the demo

`python -m regista.agents record` renders every insight (recaps included) for the preset profiles and writes a
JSON cache. `REGISTA_AGENT_CACHE` makes the API serve it, with a "cache" step at the head of each trace. A video take
then never depends on model latency or rate limits, and the trace shown is the recorded one, not a staged one.

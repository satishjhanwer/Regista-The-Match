# FAQ

Short answers to the questions people ask first. Design reasoning with numbers is in [DECISIONS.md](DECISIONS.md).

## Data and input

### Where does the input stream come from?

Today, from a file replayed as if it were live.

1. The simulator (`python -m regista.sim generate --seed 7`) writes a whole match to `data/RGS-2026-0001.json`:
   passes, carries, shots, pressures, tackles and so on, each with player coordinates. Every event is a typed model in
   [`contracts/events.py`](../backend/regista/contracts/events.py).
2. `Replay` ([`api/replay.py`](../backend/regista/api/replay.py)) keeps a cursor into that file. `advance_to(elapsed_s)`
   feeds every event up to that moment into the hot path, one at a time, exactly as if each had just arrived.
3. `Hub` ([`api/hub.py`](../backend/regista/api/hub.py)) owns the clock. About ten times a second it moves match time
   forward and broadcasts new events, metrics and overlays to every browser on `/ws`.

Play, pause, speed and seek in the UI all drive that clock, which is why a demo take is repeatable.

### How would a live feed plug in?

The hot path never sees a file, only one event at a time, so a live source replaces only the file and the cursor:

```text
data provider / tracking feed / computer-vision auto-eventing
        │  vendor format
        ▼
adapter: vendor event → Regista contract event (PassEvent, ShotEvent, ...)
        │  Event Hubs / Kafka / WebSocket
        ▼
consumer: pipeline.apply(event) on arrival → same detectors, agents, Verifier and /ws
```

The adapter is the only new code. It maps the provider's ids, coordinates and clock onto the contract: absolute metres
on a 105 × 68 pitch, plus `period`, `t` and `elapsed_s`. The clock then comes from the feed instead of the `Hub` timer.
State engine, detectors, agents, overlay contract and frontend stay unchanged. That adapter and consumer are not built
yet; the event contract is the boundary they would plug into.

### Is any of the data real?

No. Clubs (Northvale FC, Saltmere Athletic), players, venue and every event are fictional, produced by a seeded
simulator. The hackathon provides no real league data and does not allow it.

### Why build a simulator instead of using an open event dataset?

Because it can plant storylines with known answers. The demo match (seed 7) scripts a control spell, a chaos spell, a
high press from 58', three goals, a record sprint and a brace that is also a 50th career goal. A ground-truth file
records when each happens and the true model coefficients, so detectors and metrics are scored instead of eyeballed.
Same seed, byte-identical output. See D5 and D6.

### Does the app ever read the ground-truth file?

No. `*.truth.json` is read only by tests and evaluation scripts. The state engine, detectors, agents and UI never load it.

## Agents and the Verifier

### Why is the Verifier code and not another model?

The gate that keeps wrong numbers off screen must not be able to hallucinate itself. A model judging a model can agree
with a confident mistake; a comparison against computed facts cannot. Every number, name, team attribution and
language in a draft is checked mechanically against the facts the sentence cites. See D20 and D28.

### What happens when the model is wrong, slow or offline?

A rejected draft goes back to the Narrator once, with the reasons. A second rejection, a timeout or no model at all
falls back to a verified template in English, Spanish or Hindi. Nothing unverified reaches the screen, and the agent
trace shows which path a graphic took.

### Why not run the model on every event?

A match has about 2,400 events and most of them don't matter on their own. The deterministic hot path handles every
event in microseconds; agents run only when a detector fires, 40 times in the demo match. Broadcast graphics already
trail live action, so a few seconds of narration latency are acceptable there, and never on the hot path.

### What does the Analyst actually do?

It frames the moment, choosing which facts matter for this insight, through four tools over a frozen snapshot of
match state: `get_facts`, `get_state`, `get_player` and `get_window_stats`. Every number a tool returns becomes a
citable fact; the Analyst never computes or invents one. Its framing is internal and is not shown to viewers.

### How does personalization avoid changing the facts?

One detector output is one canonical `Insight`. Each viewer profile (mode, club, focus player, metric, language) gets
its own rendering of that same insight, and every rendering passes the same Verifier against the same facts. The
telling changes; the numbers cannot. The Compare viewers tab shows two renderings side by side.

### Why does Hindi come from templates in the demo?

The 3B local model wrote unreliable Hindi. `REGISTA_LLM_LANGUAGES=en,es` limits model narration to languages checked
by hand, and Hindi uses verified templates instead; the trace says so. With a stronger model, add `hi` after a manual
check.

## Running it

### Can I try it without installing anything?

Yes, once the static demo is deployed to GitHub Pages: the whole replay is precomputed into one JSON bundle and the
browser plays it, with the same live view, controls, compare view and agent traces as the local app. It covers the
presets plus a grid of viewers (analyst and casual in every language and club, Player focus on five key players);
any other choice shows the closest precomputed viewer, and live models need the local app. See D34.

### Do I need Azure or a model to run it?

No. `REGISTA_LLM_PROVIDER=none` runs everything on verified templates, with no model and no network. For the demo
experience, add `REGISTA_AGENT_CACHE=../data/RGS-2026-0001.renders.foundry-local.json` to replay the recorded Foundry
Local run, real tool calls and Verifier rejections included. Steps are in the [README](../README.md#run-it-locally).

### Why Foundry Local and not Microsoft Foundry in Azure?

No Azure subscription was available for this entry. The `foundry` provider is wired through
`regista.llm.build_chat_client()` and switches on with `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_MODEL`; nothing else
changes. Foundry Local runs the same agents on the laptop. See D11, D12 and D28.

### How fast is it?

The hot path processes the whole demo match in about 80 ms (p95 under 0.06 ms per event). A model rendering took
roughly 1.5 to 5 minutes on a CPU-only laptop, which is why the demo plays a recorded run; a cloud model would take
seconds, and the template path is instant either way. To see where the time goes in a rendering, export its
OpenTelemetry trace to a local viewer (see the README). Measured results are in the
[README](../README.md#measured-results).

### How good are the xG and pass-difficulty models?

Both are logistic models fitted on seeds 1-5 and tested on seed 7 against the simulator's true probabilities: pass
difficulty Brier 0.129 vs 0.165 for a constant rate, xG expected Brier 0.136 vs 0.163 for mean xG. Refit and report
with `python scripts/fit_models.py`. See D14 and D15.

## Extending it

### How are player ratings worked out?

From published weights in `backend/regista/state/models/ratings.json`, applied to every event. A rating starts at 6.0
and moves with goals and the quality of every shot (xG), chances created for others, completed passes weighted by how
hard they were, tackles, interceptions, pressures and saves, minus points lost to failed passes (an easy one costs
more) and lost tackles. Every rating airs with its breakdown as facts, so the Verifier checks each number. The weights
are set by hand, not fitted: no answer key says how well someone played. On training seeds they average 6.9 with a
spread of 0.6. The top-rated player of each team airs for everyone at half time and full time; every other player's
rating goes only to a viewer following them. See D33.

### Does Regista predict anything?

A little, and it keeps score. When momentum swings or a press starts, the hot path makes a checkable call about the
next 10 minutes: "Northvale create more xG than Saltmere" or "Northvale's pass completion stays below 82%". Each call
states its chance, which is its hit rate on training seeds 1-5. When the 10 minutes are up, the call is graded right
or wrong from the event stream, and the running record ("2 hits from 4 calls") goes on screen with the result. On
unseen matches the stated chances hold up (60% stated, 72% came true; 75% stated, 73% came true). The Verifier
rejects any telling that flips the verdict. See D30.

### How do I add a detector?

Subclass `Detector` in [`detect/base.py`](../backend/regista/detect/base.py): set `kind` and `cooldown_s`, and
return drafts with facts and evidence from `detect(ev, updates, st)`. Add it to `default_detectors()` in
[`detect/detectors.py`](../backend/regista/detect/detectors.py), and add a test against a planted storyline. Agents,
Verifier and overlay pick it up through the `Insight` contract.

### How do I add a language?

Add phrase tables for templates in [`agents/phrases.py`](../backend/regista/agents/phrases.py), so the fallback
works without a model. Teach the Verifier's language check about it in
[`agents/verifier.py`](../backend/regista/agents/verifier.py) (script, or stopwords for a Latin-script language). Then
add it to the language picker in the frontend. `FanProfile.language` is a plain BCP 47 tag, so the contracts don't change.

### Can other agents use Regista's match state?

Yes, over MCP. The running API serves the Analyst's own tools at `/mcp`, read-only and on the clock viewers watch, so
an outside agent gets the same numbers, labels and evidence as Regista's agents, and nothing from the future.
`python -m regista.mcp_server` runs the same tools over stdio for desktop MCP clients, with a `seek` tool. See D31.

### What would a broadcast graphics partner consume?

`OverlayPayload` messages over WebSocket: the insight with its facts and evidence, the verified rendering, and a
display directive (slot, template id, match-clock time to show it, time to live, priority). The schema is exported to
[`contracts/schema/`](../contracts/schema/), and the wire protocol is in [API.md](API.md).

### What is not built?

Cloud deployment (no Azure subscription), a live ingest adapter, computer-vision auto-eventing, and multi-match scale.

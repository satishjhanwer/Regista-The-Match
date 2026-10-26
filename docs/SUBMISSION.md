# Submission copy

Everything below is true of what shipped. Recheck the "Built with" line if the runtime changes.

## Title (max 140)

Regista: The Match, Explained and Verified, for Every Fan

## Tagline (max 300)

Regista turns a live stream of match events into broadcast overlays that explain why a moment matters, told for
each fan's mode, club, player and language. Agents built on Microsoft Agent Framework narrate, and a Verifier checks
every number against match data before it reaches the screen.

## Elevator pitch

Regista is a real-time match intelligence engine for broadcast and streaming. A deterministic analytics layer computes
pass difficulty, xG, momentum, control vs chaos and pressing shifts on every event in microseconds, and nine detectors
fire when a moment matters. A team of agents built on Microsoft Agent Framework then tells the story. An Analyst reads
match state through tools. A Narrator writes for each viewer: analyst or casual, favourite club, focus player, English,
Spanish or Hindi. A Verifier written as code rejects any sentence whose numbers, names or language the data does not
support. Rejected drafts go back with reasons, and a verified template airs if the model fails twice. The output is
timed, machine-readable overlay data, rendered in a React broadcast overlay with an agent trace that shows why every
graphic is on screen.

## Project description

Football coverage still leans on the scoreline and a few totals. The story sits between the events: a press that
starts to bite, a spell where nobody can keep the ball, a sprint that breaks the match record, a header that is also a
50th career goal. Studios can't surface those patterns at live speed, and fans can't get them in the form they watch.

Regista closes that gap with two tiers.

**The hot path is deterministic and fast.** A seeded simulator streams football-realistic events with player
coordinates. A state engine turns each one into match state in about 25 microseconds:

- pass difficulty, from a logistic model fitted offline and calibrated against held-out ground truth
- expected goals
- momentum, as an exponentially decayed threat signal
- control vs chaos, from turnover rate, sequence length and possession-transition entropy
- a pressing change-point detector (a gated CUSUM)

Nine detectors turn that state into insights. Each insight is one canonical object whose facts carry their evidence:
event ids, or metric windows.

**The warm path is agentic and grounded.** Only detected moments reach the agents, built on Microsoft Agent Framework:

- **Analyst:** frames the moment through four tools over a frozen state snapshot. Every number a tool returns becomes a
  citable fact.
- **Narrator:** writes one rendering per fan profile, directly in the target language. Every sentence cites the facts
  it uses.
- **Verifier:** deliberately code, not a model. It checks that every number matches a cited fact, digits and number
  words alike, and that each number is attributed to the right team or player. It also checks that no stranger is
  named, the language is right, and the text fits the overlay. Rejections go back to the Narrator with reasons; a
  second failure falls back to a verified template.

We ran the agents against real models on a laptop. Every failure we saw became a tested Verifier rule: a "second
goal" that was a first, a striker placed in the wrong club, a Spanish fan answered in Portuguese.

Personalization never changes facts, only the telling. An analyst gets numbers and evidence. A casual fan gets the
story and one telling stat. A player-focus viewer follows one player all match. The facts are identical in every
language. The overlay contract is timed to the match clock and prioritized per slot, ready for a broadcast rendering
partner. A React overlay with fan controls, a side-by-side compare view and a live agent trace shows it end to end.

Built with: Microsoft Agent Framework (Analyst and Narrator agents, tool calling), Microsoft Foundry Local (on-device
model runtime) RUNTIME-TBD, Python (FastAPI, analytics engine), React with TypeScript (overlay and fan experience).
Contracts flow from Pydantic to JSON Schema to TypeScript, and CI fails on drift.

## Goals

1. Explain, don't just report: every insight carries why the moment matters, with evidence.
2. Zero ungrounded numbers on screen: every number traces to a fact; enforced by the Verifier, measured by
   `scripts/eval_run.py` (every rendering on air re-checked: 31 of 31 pass).
3. Live-ready: the hot path handles a whole match in about 70 ms; agents only run on moments, and a verified template
   is always ready.
4. One intelligence, many experiences: one canonical insight stream, genuinely different renderings by mode, club,
   player and language, facts unchanged.
5. Broadcast-ready output: timed, prioritized, machine-readable overlay payloads.
6. Honest synthetic data: an open, seedable simulator with planted storylines and ground truth, used only for
   evaluation.

## Non-goals

Computer-vision auto-eventing (a future producer behind the same event contract), real clubs, players or league data,
multi-match scale, cloud deployment (no Azure subscription for this entry; everything runs locally).

## Demo video script (under 2:00)

Record against the recorded run (`REGISTA_AGENT_CACHE=../data/RGS-2026-0001.renders.json`) so every take is
identical. No music, or royalty-free only. Fictional names only.

| Time | Shot | Say |
| --- | --- | --- |
| 0:00-0:12 | Score bug at 0-0, pitch trail moving | "The scoreline never tells the story. Regista watches every event and explains why a moment matters." |
| 0:12-0:35 | Seek to 60', play: press-change side panel airs at 61:44, ribbon swings to Saltmere | "Saltmere switch to a high press. A change-point detector catches it two minutes after it starts. The numbers are on screen, and each one is computed, not generated." |
| 0:35-0:55 | 64' goal lower third; click it, trace panel: claim → fact → event evidence | "Their goal comes straight out of the press: Lindqvist wins it 27 m out, three seconds later it's in. Every sentence cites the facts it uses." |
| 0:55-1:20 | Compare viewers: same moment, analyst English vs casual Spanish / Hindi focus | "One set of facts, many viewers: an analyst in English, a Saltmere fan in Spanish, a Vukovic fan in Hindi." |
| 1:20-1:45 | Trace of the 38' goal for the Spanish fan: drafts blocked ("segundo gol"), template aired | "The model wrote 'his second goal'. It was his first. The Verifier is code, not another model. It blocked it twice, and a verified template aired instead." |
| 1:45-1:58 | Full-time recap and architecture diagram from the README | "Deterministic analytics, agents on Microsoft Agent Framework, and nothing unverified on screen." |

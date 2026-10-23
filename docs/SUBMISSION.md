# Submission copy

Recheck the technology list against what actually shipped before submitting.

## Title (max 140)
Regista: The Match, Explained and Verified, for Every Fan

## Tagline (max 300)
Regista reads every synthetic match event in real time, explains why moments matter, verifies every claim against match data, and renders broadcast-ready overlays and recaps personalized by club, player, viewing mode and language. Built on Microsoft Foundry, Agent Framework and Azure Container Apps.

## Elevator pitch
Regista is a real-time match intelligence engine that turns synthetic football events into explained, verified and personalized stories for broadcast and streaming. A deterministic analytics layer computes pass difficulty, xG, momentum, control vs chaos and pressing shifts as events arrive. When a moment matters, a team of agents built on Microsoft Agent Framework and Microsoft Foundry explains why. The team is an Analyst that reads match state, a Narrator that tells the story, and a Verifier that rejects any claim the data does not support. The output is timed, machine-readable overlay data, rendered live in a React broadcast UI and tailored to each fan by viewing mode, favorite club, player focus and language. It runs on Azure Container Apps.

## Project description
Football coverage still leans on the scoreline and a handful of totals. The real story sits in the patterns between events: a press that quietly breaks down, a midfielder who suddenly controls the tempo, a team that keeps possession but creates nothing. Studios can't surface those patterns at live speed. Fans can't get them in a form that matches how they watch.

Regista closes that gap with a two-tier architecture.

The hot path is deterministic and fast. A synthetic match simulator streams football-realistic events with player coordinates: passes, shots, tackles, possession changes and pressure events. A stateful analytics engine turns them into match state within milliseconds. That state includes pass difficulty as a probability of completion, shot quality, an exponentially weighted momentum signal, an entropy-based control vs chaos score, and change-point detection on pressing intensity and game rhythm. Moment detectors watch this state and fire when something meaningful happens.

The warm path is agentic and grounded. Each detected moment goes to a multi-agent pipeline:
- The Analyst queries match state through tools and never invents a number.
- The Narrator explains why the moment matters in plain football language.
- The Verifier checks every factual claim against the computed state. Anything ungrounded is blocked before it reaches the screen.
- The same pipeline produces live narratives, player-performance context, milestones and full-time recaps.

Every insight becomes one canonical, timestamped object carrying its own evidence. A personalization layer then decides what each viewer sees and how it is told: an analyst gets numbers and evidence, a casual fan gets the story with one telling stat, a player-focus viewer follows one player all match, and each of them can read it in their own language with facts identical across languages.

The overlay contract is machine-readable and synchronized to the match clock, ready for a broadcast rendering partner. A React overlay and fan control panel show it working end to end.

Built with: Microsoft Foundry (models and evaluations), Microsoft Agent Framework (multi-agent orchestration), Azure Container Apps (hosting), Azure Monitor / Application Insights with OpenTelemetry (agent tracing), Azure Developer CLI (one-command deployment), Python (FastAPI, analytics engine), and React with TypeScript (overlay and fan experience).

## Goals
1. Explain, don't just report: every insight answers why the moment matters.
2. Zero ungrounded claims on screen: every number traces to computed state via evidence refs; enforced by the Verifier and measured by a groundedness eval.
3. Live-ready latency: metrics and overlays under 200 ms from ingestion; narratives within a few seconds of a moment.
4. One intelligence, many experiences: one canonical insight stream, genuinely different experiences by mode, club, player and language, facts unchanged.
5. Broadcast-ready output: timed, prioritized, machine-readable overlay payloads.
6. Realistic synthetic data as a deliverable: an open, seedable simulator with spatial data and ground truth.
7. Production-shaped: one-command deploy, tested analytics, traced agents, latency budgets, no secrets in the repo.

## Non-goals
Computer-vision auto-eventing (defined interface for future work), real clubs/players/league data, multi-match scale.

## Demo video script (under 2:00)
| Time | Shot |
|---|---|
| 0:00-0:15 | Problem: the scoreline doesn't tell the story |
| 0:15-0:45 | Live overlay on the simulated match; the 58' press shift triggers a "why it matters" card |
| 0:45-1:15 | Split screen, same moment: analyst mode in English vs casual player-focus mode in Hindi/Spanish |
| 1:15-1:35 | Agent trace: Analyst -> Narrator -> Verifier, one claim rejected and fixed |
| 1:35-1:55 | Architecture slide + auto-generated full-time recap |

Record against a cached run so rate limits cannot ruin a take. No music, or royalty-free only.

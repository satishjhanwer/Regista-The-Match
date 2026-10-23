# Hackathon brief, rubric and rules

*Inside the Game: Developer Hackathon*, presented by Microsoft and the Premier League, on Microsoft Innovation Studio.
Challenge: **The Synthetic Match Insights Engine for Premier League Studio**.

## Key dates

- Hackathon window: 29 Sep to 20 Oct 2026 (registration closed 20 Oct).
- **Submission deadline: 27 Oct 2026, 11:59 PM Pacific Time** (28 Oct, 12:29 PM IST).
- Rules: https://aka.ms/insidethegame/rules (not fetchable by tools; read in a browser before submitting).

## Challenge requirements (condensed from the brief)

Build an AI-powered solution on Azure that turns **synthetic, football-realistic events** into explainable match intelligence,
real-time narratives and automated recaps for studio, broadcast or streaming, personalized for fans in any market.
No real Premier League data is provided or allowed.

### (i) One pipeline, five stages
- [ ] **Ingest** synthetic events as they happen: passes, shots, tackles, possession changes, pressure events, match metadata.
- [ ] **Interpret** into meaningful statistics, patterns and context.
- [ ] **Explain** why a moment matters, not only that it happened.
- [ ] **Render** the insight as something that sits on screen alongside the match (timed, machine-readable, overlay-ready,
      as a broadcast rendering partner would consume).
- [ ] **Personalize** so a data-hungry analyst and a casual fan get genuinely different experiences: viewing modes, favorite club(s),
      favorite player(s), player-focus mode across the match, language, a single metric of interest.
- A project that only generates metrics has no audience; one that only personalizes has nothing to personalize. Do both.

### (ii) Real-time match intelligence (features to consider)
- [ ] Player identification: real-time name tagging, optional speed and distance indicators when thresholds are hit.
- [ ] Pass quality: distance, accuracy, pass difficulty rating.
- [ ] Speed metrics: ball speed, shot speed.
- [ ] Auto-eventing from video (optional; **out of scope for Regista**, documented as a future producer behind the event contract).

### (iii) Narrative generation
- [ ] Key narratives, player-performance context, notable milestones, match recaps.

### (iv) Explainability
- [ ] Why moments matter: control vs chaos, tactical pressure changes, game rhythm patterns.

### (v) Data innovation
- [x] Create or extend a synthetic football-realistic dataset (passes, shots, tackles, possession changes, pressure, metadata).

### (vi) Multi-language storytelling
- [ ] Clear natural-language output in multiple languages.

## What to submit

- A newly built project meeting the requirements.
- Project pitch/description: what was built, which Microsoft and Azure technologies, what it does, what problem it solves.
- **Demo video under 2 minutes** (judges may stop at 2:00), showing the project running on its platform, public URL on
  YouTube / Vimeo / Facebook Video / Youku, linked on the project page. **No third-party trademarks, copyrighted music or
  material without permission.**
- **Public GitHub repo URL.** Private repos are not considered.

## Judging rubric (each 20%)

1. **Technological implementation:** quality engineering practices, effective use of hero technologies, well-structured, documented, maintainable code.
2. **Agentic design and innovation:** creative agentic patterns, sophisticated orchestration or multi-agent collaboration, novel AI implementation.
3. **Real-world impact and applicability:** significance of the problem, production deployment readiness, impact on developers/businesses/users.
4. **User experience and presentation:** intuitive UX, clear communication of value in the demo, balanced frontend and backend.
5. **Adherence to category:** matches the challenge description above.

Equal weights mean a weak area costs more than a single standout gains. Hero technologies were not listed explicitly; the
hackathon's own Reactor session used AKS and Azure Container Apps, and prior Innovation Studio hackathons rewarded
Microsoft Foundry and Microsoft Agent Framework / MCP multi-agent orchestration.

## Project page fields (Innovation Studio)

- Title: **Regista: The Match, Explained and Verified, for Every Fan**
- Tagline, description, goals: see `docs/SUBMISSION.md`.
- Keywords: Azure OpenAI, Microsoft Foundry, Agent Framework, AI Agents, Real-Time Analytics, Explainable AI, Football Analytics,
  Synthetic Data, Personalization, Multilingual NLG, Broadcast Overlays.

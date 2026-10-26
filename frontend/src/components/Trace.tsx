/**
 * Explainability: the insight feed and the agent trace for one rendering.
 * The trace shows Analyst -> Narrator -> Verifier steps and maps every claim to the
 * facts it cites and to the evidence behind those facts (events and metric windows).
 */

import type { Fact, Insight, OverlayMessage, RenderedInsight, TraceStep } from "../contracts/stream";
import { elapsedText, factText, KIND_LABEL } from "../lib/format";

/** Insights received for this viewer, newest first. */
export function Feed({ items, selected, onSelect }: { items: OverlayMessage[]; selected: string | null; onSelect: (m: OverlayMessage) => void }) {
  return (
    <section className="panel feed">
      <div className="panel-title">
        Insights <span className="count">{items.length}</span>
      </div>
      {items.length === 0 && <p className="empty">Moments appear here as the detectors fire.</p>}
      <ol>
        {[...items].reverse().map((m) => {
          const { insight, rendered } = m.payload;
          return (
            <li key={insight.insight_id}>
              <button className={selected === insight.insight_id ? "on" : ""} onClick={() => onSelect(m)}>
                <span className="f-clock">{insight.clock.display}</span>
                <span className={`f-kind kind-${insight.kind}`}>{KIND_LABEL[insight.kind]}</span>
                <span className={`f-head lang-${rendered.language}`}>{rendered.headline}</span>
                <span className={`f-src src-${m.source}`}>{m.source.replace("_", " ")}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

const AGENT_LABEL: Record<TraceStep["agent"], string> = {
  analyst: "Analyst",
  narrator: "Narrator",
  verifier: "Verifier",
  template: "Template",
  cache: "Recorded run",
};

function StepDetail({ step, facts }: { step: TraceStep; facts: Map<string, Fact> }) {
  const d = step.detail as Record<string, unknown>;
  if (step.agent === "analyst") {
    const ids = (d.fact_ids as string[] | undefined) ?? [];
    const calls = (d.tool_calls as { tool: string; args: Record<string, unknown> }[] | undefined) ?? [];
    return (
      <>
        {typeof d.angle === "string" && <p className="angle">“{d.angle}”</p>}
        {calls.length > 0 && (
          <p className="tools">
            tools:{" "}
            {calls.map((c, i) => (
              <code key={i}>
                {c.tool}({Object.values(c.args).join(", ")})
              </code>
            ))}
          </p>
        )}
        <p className="picked">selected {ids.map((id) => facts.get(id)?.label ?? id).join(" · ")}</p>
        {typeof d.error === "string" && <p className="err">{d.error}</p>}
      </>
    );
  }
  if (step.agent === "narrator") {
    const claims = (d.claims as { text: string }[] | undefined) ?? [];
    return (
      <>
        {typeof d.headline === "string" && <p className="draft-head">{d.headline}</p>}
        {claims.map((c, i) => (
          <p key={i} className="draft">
            {c.text}
          </p>
        ))}
        {typeof d.error === "string" && <p className="err">{d.error}</p>}
      </>
    );
  }
  if (step.agent === "verifier") {
    const notes = (d.notes as string[] | undefined) ?? [];
    return notes.length ? (
      <ul className="notes">
        {notes.map((n, i) => (
          <li key={i}>{n}</li>
        ))}
      </ul>
    ) : (
      <p className="ok-line">{String(d.claims ?? "")} claims checked, every number and name matches a cited fact</p>
    );
  }
  return null;
}

/** Each claim with the facts it cites and the evidence behind each fact. */
export function ClaimMap({ insight, rendered }: { insight: Insight; rendered: RenderedInsight }) {
  const facts = new Map(insight.facts.map((f) => [f.fact_id, f]));
  return (
    <ol className="claims">
      {rendered.claims.map((c, i) => (
        <li key={i}>
          <p className={`claim lang-${rendered.language}`}>{c.text}</p>
          {c.fact_ids.length === 0 && <span className="colour-tag">fan colour, no numbers allowed</span>}
          <div className="cites">
            {c.fact_ids.map((id) => {
              const f = facts.get(id);
              if (!f) return null;
              return (
                <span key={id} className="fact-chip">
                  <b>{f.label}</b> {factText(f)}
                  {f.previous_value !== null && <em> (was {f.previous_value})</em>}
                  <span className="evidence">
                    {f.evidence.map((e, j) => (
                      <span key={j} className={`ev ev-${e.kind}`}>
                        {e.kind === "event" ? `event ${e.ref.split("-").pop()}` : `${e.ref}${e.window_start_s !== null ? ` ${elapsedText(e.window_start_s)}–${elapsedText(e.window_end_s)}` : ""}`}
                      </span>
                    ))}
                  </span>
                </span>
              );
            })}
          </div>
        </li>
      ))}
    </ol>
  );
}

/** Why a graphic is on screen: the agent steps that produced it and its claim-to-fact map. */
export function TracePanel({ insight, rendered, trace, source }: { insight: Insight; rendered: RenderedInsight; trace: TraceStep[]; source: string }) {
  const facts = new Map(insight.facts.map((f) => [f.fact_id, f]));
  return (
    <section className="panel trace">
      <div className="panel-title">
        Why you see this <span className={`f-src src-${source}`}>{source.replace("_", " ")}</span>
      </div>
      <p className={`t-head lang-${rendered.language}`}>
        <span className="lt-clock">{insight.clock.display}</span> {rendered.headline}
      </p>
      <ol className="steps">
        {trace.map((s, i) => (
          <li key={i} className={`step st-${s.status} ag-${s.agent}`}>
            <div className="step-head">
              <span className="ag">{AGENT_LABEL[s.agent]}</span>
              <span className="act">{s.action}</span>
              <span className="st">{s.status}</span>
              <span className="ms">{s.ms} ms</span>
            </div>
            <StepDetail step={s} facts={facts} />
          </li>
        ))}
      </ol>
      <div className="panel-subtitle">Claims and the facts they cite</div>
      <ClaimMap insight={insight} rendered={rendered} />
    </section>
  );
}

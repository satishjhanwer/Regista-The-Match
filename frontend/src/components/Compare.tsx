/**
 * Same moment, two viewers: renders one insight for two profiles side by side,
 * and shows that both stand on the identical set of facts.
 */

import { useEffect, useState } from "react";

import type { FanProfile, Insight, MatchMeta, RenderResponse } from "../contracts/stream";
import { api, type ProfileParams } from "../lib/api";
import { factText, KIND_LABEL, LANGS } from "../lib/format";
import { ClaimMap } from "./Trace";

const DEFAULT_A: ProfileParams = { mode: "analyst", lang: "en", team: "", player: "" };
const DEFAULT_B: ProfileParams = { mode: "casual", lang: "hi", team: "NVL", player: "NVL-09" };

function ProfileEditor({ meta, value, onChange }: { meta: MatchMeta; value: ProfileParams; onChange: (p: ProfileParams) => void }) {
  const players = [...meta.home.players, ...meta.away.players];
  return (
    <div className="cmp-editor">
      <select value={value.mode} onChange={(e) => onChange({ ...value, mode: e.target.value as FanProfile["mode"] })}>
        <option value="analyst">Analyst</option>
        <option value="casual">Casual</option>
        <option value="player_focus">Player focus</option>
      </select>
      <select value={value.lang} onChange={(e) => onChange({ ...value, lang: e.target.value })}>
        {LANGS.map((l) => (
          <option key={l.code} value={l.code}>
            {l.label}
          </option>
        ))}
      </select>
      <select value={value.team ?? ""} onChange={(e) => onChange({ ...value, team: e.target.value })}>
        <option value="">Neutral</option>
        <option value={meta.home.team_id}>{meta.home.name} fan</option>
        <option value={meta.away.team_id}>{meta.away.name} fan</option>
      </select>
      <select value={value.player ?? ""} onChange={(e) => onChange({ ...value, player: e.target.value })}>
        <option value="">No focus player</option>
        {players.map((p) => (
          <option key={p.player_id} value={p.player_id}>
            {p.short_name}
          </option>
        ))}
      </select>
    </div>
  );
}

function Card({ res }: { res: RenderResponse | null }) {
  if (!res) return <div className="cmp-card loading">rendering…</div>;
  const r = res.rendered;
  return (
    <div className={`cmp-card lang-${r.language}`}>
      <div className="lt-kicker">
        <span className="chip">{r.mode.replace("_", " ")}</span>
        <span className="chip ghost">{r.language}</span>
        <span className={`verified ${r.verification.status}`}>✓ {r.verification.status}</span>
      </div>
      <div className="lt-headline">{r.headline}</div>
      <div className="lt-body">{r.body}</div>
      {r.stat_callout && (
        <div className="sp-stat">
          <span className="value">{r.stat_callout.value}</span>
          <span className="label">{r.stat_callout.label}</span>
        </div>
      )}
      <ClaimMap insight={res.insight} rendered={r} />
    </div>
  );
}

/** One insight rendered for two editable profiles, beside the shared facts both may cite. */
export function CompareView({ meta }: { meta: MatchMeta }) {
  const [insights, setInsights] = useState<Insight[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [a, setA] = useState<ProfileParams>(DEFAULT_A);
  const [b, setB] = useState<ProfileParams>(DEFAULT_B);
  const [ra, setRa] = useState<RenderResponse | null>(null);
  const [rb, setRb] = useState<RenderResponse | null>(null);

  const refresh = () =>
    api.insights().then((list) => {
      setInsights(list);
      if (!selected && list.length) setSelected((list.find((i) => i.kind === "press_change") ?? list[list.length - 1]).insight_id);
    });

  useEffect(() => {
    refresh().catch(console.error);
  }, []);

  useEffect(() => {
    if (!selected) return;
    setRa(null);
    setRb(null);
    api.render(selected, a).then(setRa).catch(console.error);
    api.render(selected, b).then(setRb).catch(console.error);
  }, [selected, a, b]);

  const insight = insights.find((i) => i.insight_id === selected);
  const citedA = new Set(ra?.rendered.claims.flatMap((c) => c.fact_ids));
  const citedB = new Set(rb?.rendered.claims.flatMap((c) => c.fact_ids));

  return (
    <div className="compare">
      <div className="cmp-bar">
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          {insights.length === 0 && <option value="">Play the match to reach some moments</option>}
          {insights.map((i) => (
            <option key={i.insight_id} value={i.insight_id}>
              {i.clock.display} · {KIND_LABEL[i.kind]} · {i.why_it_matters_hint.slice(0, 70)}
            </option>
          ))}
        </select>
        <button onClick={() => refresh()}>Refresh</button>
      </div>
      {insight && (
        <div className="cmp-grid">
          <div>
            <ProfileEditor meta={meta} value={a} onChange={setA} />
            <Card res={ra} />
          </div>
          <div className="cmp-facts">
            <div className="panel-title">One set of facts</div>
            <p className="empty">Both renderings may only cite these. Personalization changes the telling, never the facts.</p>
            <ul>
              {insight.facts.map((f) => (
                <li key={f.fact_id}>
                  <span className={`dot ${citedA.has(f.fact_id) ? "on" : ""}`} title="cited by left" />
                  <span className="fl">{f.label}</span>
                  <b>{factText(f)}</b>
                  <span className={`dot ${citedB.has(f.fact_id) ? "on" : ""}`} title="cited by right" />
                </li>
              ))}
            </ul>
          </div>
          <div>
            <ProfileEditor meta={meta} value={b} onChange={setB} />
            <Card res={rb} />
          </div>
        </div>
      )}
    </div>
  );
}

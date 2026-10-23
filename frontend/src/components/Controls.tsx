// Replay transport and the fan control panel.

import { useState } from "react";

import type { FanProfile, MatchMeta } from "../contracts/stream";
import { api, type ProfileParams } from "../lib/api";
import { LANGS } from "../lib/format";

const SPEEDS = [1, 5, 10, 20, 60];

export function Transport({ playing, speed, minute }: { playing: boolean; speed: number; minute: number }) {
  const [drag, setDrag] = useState<number | null>(null);
  const send = (action: "play" | "pause" | "speed" | "seek" | "restart", extra: { value?: number; minute?: number } = {}) =>
    api.control({ action, value: extra.value ?? null, minute: extra.minute ?? null }).catch((e) => console.error(e));
  return (
    <div className="transport">
      <button className="tp-play" onClick={() => send(playing ? "pause" : "play")} aria-label={playing ? "Pause" : "Play"}>
        {playing ? "❚❚" : "►"}
      </button>
      <button onClick={() => send("restart")} title="Restart">
        ↺
      </button>
      <input
        type="range"
        min={0}
        max={90}
        step={0.5}
        value={drag ?? Math.min(90, minute)}
        onChange={(e) => setDrag(Number(e.target.value))}
        onPointerUp={() => {
          if (drag !== null) send("seek", { minute: drag });
          setDrag(null);
        }}
        aria-label="Seek match minute"
      />
      <span className="tp-minute">{Math.floor(drag ?? minute)}′</span>
      <div className="tp-speed" role="group" aria-label="Replay speed">
        {SPEEDS.map((s) => (
          <button key={s} className={s === speed ? "on" : ""} onClick={() => send("speed", { value: s })}>
            {s}×
          </button>
        ))}
      </div>
    </div>
  );
}

const MODES: { id: FanProfile["mode"]; label: string; hint: string }[] = [
  { id: "analyst", label: "Analyst", hint: "every number, with evidence" },
  { id: "casual", label: "Casual", hint: "the story, one telling stat" },
  { id: "player_focus", label: "Player focus", hint: "follow one player all match" },
];

const METRICS = [
  { id: "", label: "None" },
  { id: "press", label: "Pressing" },
  { id: "xg", label: "Chances (xG)" },
  { id: "momentum", label: "Momentum" },
  { id: "speed", label: "Speed" },
];

export function FanPanel({ meta, presets, params, onChange }: { meta: MatchMeta; presets: FanProfile[]; params: ProfileParams; onChange: (p: ProfileParams) => void }) {
  const set = (patch: Partial<ProfileParams>) => onChange({ ...params, profile: undefined, ...patch });
  const players = [meta.home, meta.away].flatMap((t) => t.players.map((p) => ({ ...p, team: t.short_name })));
  return (
    <section className="panel fan-panel">
      <div className="panel-title">Your broadcast</div>
      <div className="presets">
        {presets.map((p) => (
          <button
            key={p.profile_id}
            className={params.profile === p.profile_id ? "on" : ""}
            onClick={() =>
              onChange({
                profile: p.profile_id,
                mode: p.mode,
                lang: p.language,
                team: p.favorite_team_id ?? "",
                player: p.focus_player_id ?? "",
                metric: p.metric_of_interest ?? "",
              })
            }
          >
            {p.profile_id}
          </button>
        ))}
      </div>
      <label>Viewing mode</label>
      <div className="seg">
        {MODES.map((m) => (
          <button key={m.id} className={params.mode === m.id ? "on" : ""} onClick={() => set({ mode: m.id })} title={m.hint}>
            {m.label}
          </button>
        ))}
      </div>
      <label>Language</label>
      <div className="seg">
        {LANGS.map((l) => (
          <button key={l.code} className={params.lang === l.code ? "on" : ""} onClick={() => set({ lang: l.code })}>
            {l.label}
          </button>
        ))}
      </div>
      <label>Favourite club</label>
      <div className="seg">
        {[{ id: "", name: "Neutral" }, { id: meta.home.team_id, name: meta.home.name }, { id: meta.away.team_id, name: meta.away.name }].map((t) => (
          <button key={t.id} className={(params.team ?? "") === t.id ? "on" : ""} onClick={() => set({ team: t.id })}>
            {t.name}
          </button>
        ))}
      </div>
      <label htmlFor="focus">Focus player</label>
      <select id="focus" value={params.player ?? ""} onChange={(e) => set({ player: e.target.value })}>
        <option value="">None</option>
        {players.map((p) => (
          <option key={p.player_id} value={p.player_id}>
            {p.team} #{p.shirt} {p.name} ({p.role})
          </option>
        ))}
      </select>
      <label htmlFor="metric">Metric of interest</label>
      <select id="metric" value={params.metric ?? ""} onChange={(e) => set({ metric: e.target.value })}>
        {METRICS.map((m) => (
          <option key={m.id} value={m.id}>
            {m.label}
          </option>
        ))}
      </select>
    </section>
  );
}

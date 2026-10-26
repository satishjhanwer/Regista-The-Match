/**
 * Live match state on the client: a pure reducer over stream messages.
 */

import type {
  FanProfile,
  Insight,
  MomentumPoint,
  LiveMetrics,
  MatchMeta,
  OverlayMessage,
  StreamClock,
  StreamContract,
  StreamEvent,
  TickMessage,
} from "../contracts/stream";

/** Any server message on the overlay WebSocket. */
export type StreamMessage = StreamContract["message"];

/** A moment marked on the momentum ribbon. */
export interface Marker {
  minute: number;
  kind: "goal" | "press" | "chaos";
  team: string | null;
  label: string;
}

/** Everything the live view knows, built only from stream messages and history backfills. */
export interface LiveState {
  connected: boolean;
  meta: MatchMeta | null;
  profile: FanProfile | null;
  clock: StreamClock | null;
  score: Record<string, number>;
  playing: boolean;
  speed: number;
  metrics: LiveMetrics | null;
  events: StreamEvent[];
  /** Sampled momentum index; `gap` marks a sample after a jump (seek or join), so no line is drawn across it. */
  momentum: { minute: number; index: number; gap: boolean }[];
  overlays: OverlayMessage[];
  markers: Marker[];
  resets: number;
}

/** Raw events kept for the pitch trail and player-tag positions. */
export const MAX_EVENTS = 60;

/** State before the socket says hello. */
export const initialLive: LiveState = {
  connected: false,
  meta: null,
  profile: null,
  clock: null,
  score: {},
  playing: false,
  speed: 10,
  metrics: null,
  events: [],
  momentum: [],
  overlays: [],
  markers: [],
  resets: 0,
};

/** Football minute: stoppage folds into 44.99 / 89.99 (same as the backend's match_minute). */
export function matchMinute(period: number, t: number): number {
  return Math.min(t, 2699.99) / 60 + (period === 2 ? 45 : 0);
}

/** Stream messages plus the client's own connection and history-backfill actions. */
export type LiveAction =
  | StreamMessage
  | { type: "connected"; value: boolean }
  | { type: "history"; momentum: MomentumPoint[]; insights: Insight[] };

function markerKey(m: Marker): string {
  return `${m.kind}-${m.team}-${m.minute.toFixed(1)}`;
}

function addMarkers(existing: Marker[], extra: Marker[]): Marker[] {
  const seen = new Set(existing.map(markerKey));
  const fresh = extra.filter((m) => !seen.has(markerKey(m)));
  return fresh.length ? [...existing, ...fresh] : existing;
}

/** Markers derivable from canonical insights (goal, press change, chaos spell). */
export function markersFrom(insights: Insight[]): Marker[] {
  const out: Marker[] = [];
  for (const ins of insights) {
    const minute = matchMinute(ins.clock.period, ins.clock.t);
    const team = ins.entities.team_ids[0] ?? null;
    if (ins.kind === "goal") out.push({ minute, kind: "goal", team, label: String(ins.facts[0]?.value ?? "") });
    if (ins.kind === "press_change") out.push({ minute, kind: "press", team, label: ins.why_it_matters_hint });
    if (ins.kind === "control_vs_chaos" && ins.entities.team_ids.length === 0) out.push({ minute, kind: "chaos", team: null, label: ins.why_it_matters_hint });
  }
  return out;
}

/** True when a tick jumped past the last momentum sample (connect or seek): time to backfill history. */
export function needsHistory(s: LiveState, m: TickMessage): boolean {
  const last = s.momentum[s.momentum.length - 1];
  return !last || matchMinute(m.clock.period, m.clock.t) - last.minute > 1.5;
}

/** Pure reducer from live state and one action to the next state. */
export function reduce(s: LiveState, m: LiveAction): LiveState {
  switch (m.type) {
    case "connected":
      return { ...s, connected: m.value };
    case "history": {
      if (m.momentum.length === 0) return s; // nothing played yet: keep live samples
      const momentum = m.momentum.map((p, i) => ({ minute: p.minute, index: p.index, gap: i === 0 }));
      return { ...s, momentum, markers: addMarkers([], markersFrom(m.insights)) };
    }
    case "hello":
      return { ...initialLive, connected: true, meta: m.match, profile: m.profile, clock: m.replay.clock, playing: m.replay.playing, speed: m.replay.speed, resets: s.resets };
    case "tick": {
      const minute = matchMinute(m.clock.period, m.clock.t);
      const last = s.momentum[s.momentum.length - 1];
      const gap = !last || minute - last.minute > 1.5;
      const momentum = !last || minute - last.minute >= 0.2 ? [...s.momentum, { minute, index: m.metrics.momentum_index, gap }] : s.momentum;
      return { ...s, clock: m.clock, score: m.score, playing: m.playing, speed: m.speed, metrics: m.metrics, momentum };
    }
    case "events": {
      const goals: Marker[] = m.events
        .filter((e) => e.type === "shot" && e.outcome === "goal")
        .map((e) => ({ minute: matchMinute(e.period, e.t), kind: "goal", team: e.team, label: e.player ?? "" }));
      return { ...s, events: [...s.events, ...m.events].slice(-MAX_EVENTS), markers: addMarkers(s.markers, goals) };
    }
    case "overlay": {
      const ins = m.payload.insight;
      const extra: Marker[] = [];
      const minute = matchMinute(ins.clock.period, ins.clock.t);
      if (ins.kind === "press_change") extra.push({ minute, kind: "press", team: ins.entities.team_ids[0] ?? null, label: m.payload.rendered.headline });
      if (ins.kind === "control_vs_chaos" && ins.entities.team_ids.length === 0) extra.push({ minute, kind: "chaos", team: null, label: m.payload.rendered.headline });
      return { ...s, overlays: [...s.overlays, m], markers: addMarkers(s.markers, extra) };
    }
    case "reset":
      return { ...s, events: [], momentum: [], overlays: [], markers: [], resets: s.resets + 1 };
    case "error":
      console.warn("stream error:", m.error);
      return s;
  }
}

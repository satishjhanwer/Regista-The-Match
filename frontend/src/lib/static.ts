/**
 * Static demo mode: the whole replay precomputed by `backend/scripts/export_static.py`, played in the browser.
 *
 * `StaticHub` is a port of the backend's `Replay` and `Hub`: one shared clock, the same controls, the same stream
 * messages (hello, tick, events, overlay, reset). The live view cannot tell it from the WebSocket, so every
 * component works unchanged. Renderings exist for a fixed set of viewer profiles; any other choice is served by the
 * closest one (see {@link resolveProfile}).
 */

import type {
  ControlRequest,
  DisplayDirective,
  FanProfile,
  Insight,
  LiveMetrics,
  MatchMeta,
  MomentumPoint,
  OverlayMessage,
  RenderResponse,
  RenderedInsight,
  ReplayStatus,
  StreamClock,
  StreamEvent,
  TickMessage,
  TraceStep,
} from "../contracts/stream";
import type { ProfileParams } from "./api";
import type { StreamMessage } from "./live";

/** True in a build made with `VITE_STATIC=1`: no backend, the replay comes from the bundle. */
export const STATIC = import.meta.env.VITE_STATIC === "1";

/** One precomputed rendering of an insight for a profile. `display` is null when that viewer would not see it. */
export interface RenderRow {
  id: string;
  source: OverlayMessage["source"];
  rendered: RenderedInsight;
  display: DisplayDirective | null;
  trace: TraceStep[];
  /** Present when the Analyst promoted tool facts into this rendering. */
  insight?: Insight;
}

/** The precomputed replay (layout written by export_static.py). */
export interface Bundle {
  version: number;
  match: MatchMeta;
  presets: FanProfile[];
  profiles: FanProfile[];
  end_s: number;
  events: StreamEvent[];
  elapsed: number[];
  match_clock: number[];
  ticks: { score: Record<string, number>; metrics: LiveMetrics }[];
  /** [elapsed_s, minute, index] */
  momentum: [number, number, number][];
  insights: Record<string, Insight>;
  /** [elapsed_s, insight_id], in the order the replay produced them */
  fired: [number, string][];
  renders: Record<string, RenderRow[]>;
  recorded_from: string | null;
}

const PERIOD_S = 2700;
const SPEED_MIN = 0.25;
const SPEED_MAX = 120;
const LANGS = ["en", "es", "hi"];

/** Broadcast clock string, as the backend's format_clock: "23:41", stoppage "45+01:12". */
export function formatClock(period: number, t: number): string {
  const base = period === 1 ? 0 : 45;
  const two = (n: number) => String(Math.floor(n)).padStart(2, "0");
  if (t < PERIOD_S) return `${base + Math.floor(t / 60)}:${two(t % 60)}`;
  const extra = t - PERIOD_S;
  return `${base + 45}+${two(extra / 60)}:${two(extra % 60)}`;
}

function minuteOf(period: number, t: number): number {
  return Math.min(t, PERIOD_S - 0.01) / 60 + (period === 2 ? 45 : 0);
}

/**
 * The profile to serve for a request: the exact precomputed one, or the closest with the same mode and language
 * (focus player counts most, then club, then metric), or the first preset. `exact` says which.
 */
export function resolveProfile(b: Bundle, q: ProfileParams): { profile: FanProfile; exact: boolean } {
  const base = b.presets.find((p) => p.profile_id === q.profile) ?? b.presets[0];
  const want = {
    mode: q.mode || base.mode,
    language: q.lang && LANGS.includes(q.lang) ? q.lang : base.language,
    team: (q.team !== undefined ? q.team : base.favorite_team_id) || null,
    player: (q.player !== undefined ? q.player : base.focus_player_id) || null,
    metric: (q.metric !== undefined ? q.metric : base.metric_of_interest) || null,
  };
  let best: FanProfile | null = null;
  let bestScore = -1;
  for (const p of b.profiles) {
    if (p.mode !== want.mode || p.language !== want.language) continue;
    const score =
      4 * Number((p.focus_player_id ?? null) === want.player) +
      2 * Number((p.favorite_team_id ?? null) === want.team) +
      Number((p.metric_of_interest ?? null) === want.metric);
    if (score > bestScore) [best, bestScore] = [p, score];
  }
  return best ? { profile: best, exact: bestScore === 7 } : { profile: b.presets[0], exact: false };
}

/** A connected viewer: where to send messages, and the profile it is served. */
export interface StaticViewer {
  profile: FanProfile;
  send: (msg: StreamMessage) => void;
}

/** The backend hub, in the browser: shared replay clock, controls, and per-viewer overlays from the bundle. */
export class StaticHub {
  readonly b: Bundle;
  playing: boolean;
  speed = 10;
  cursor = 0;
  clockS = 0;
  private firedIdx = 0;
  private viewers = new Set<StaticViewer>();
  private rows = new Map<string, Map<string, RenderRow>>();

  constructor(bundle: Bundle, autoplay = true) {
    this.b = bundle;
    this.playing = autoplay;
    for (const [pid, rows] of Object.entries(bundle.renders)) this.rows.set(pid, new Map(rows.map((r) => [r.id, r])));
  }

  /** True once the last event has been applied. */
  get finished(): boolean {
    return this.cursor >= this.b.events.length;
  }

  /** Broadcast clock at the replay time, as Replay.clock(). */
  clock(): StreamClock {
    const i = this.cursor ? this.cursor - 1 : 0;
    const last = this.b.events[i];
    const t = last.type !== "period_end" ? last.t + Math.max(0, this.clockS - this.b.elapsed[i]) : last.t;
    const round = (x: number) => Math.round(x * 100) / 100;
    return {
      period: last.period,
      t: round(t),
      match_clock_s: round(this.b.match_clock[i] + (t - last.t)),
      elapsed_s: round(this.clockS),
      display: formatClock(last.period, t),
    };
  }

  /** Replay status, as REST and hello report it. */
  status(): ReplayStatus {
    return { playing: this.playing, speed: this.speed, finished: this.finished, clock: this.clock(), viewers: this.viewers.size };
  }

  /** Clock, score and the live metrics after the last applied event. */
  tick(): TickMessage {
    const last = this.cursor ? this.b.ticks[this.cursor - 1] : null;
    const teams = [this.b.match.home.team_id, this.b.match.away.team_id];
    const empty: LiveMetrics = { momentum_index: 0, momentum: {}, chaos: null, control: {}, xg: {}, pressed_share: {}, press_cusum: {} };
    return {
      type: "tick",
      clock: this.clock(),
      score: last?.score ?? Object.fromEntries(teams.map((t) => [t, 0])),
      playing: this.playing,
      speed: this.speed,
      metrics: last?.metrics ?? empty,
    };
  }

  private advanceTo(elapsed: number): { events: StreamEvent[]; moments: string[] } {
    const target = Math.min(elapsed, this.b.end_s);
    const events: StreamEvent[] = [];
    while (this.cursor < this.b.events.length && this.b.elapsed[this.cursor] <= target) events.push(this.b.events[this.cursor++]);
    const moments: string[] = [];
    while (this.firedIdx < this.b.fired.length && this.b.fired[this.firedIdx][0] <= target) moments.push(this.b.fired[this.firedIdx++][1]);
    this.clockS = Math.max(this.clockS, target);
    return { events, moments };
  }

  /** Advance by match seconds: events, a tick, then the overlays each viewer's profile would see. */
  step(matchSeconds: number): void {
    const { events, moments } = this.advanceTo(this.clockS + matchSeconds);
    if (events.length) this.broadcast({ type: "events", events });
    this.broadcast(this.tick());
    for (const id of moments) for (const v of this.viewers) this.dispatch(id, v);
  }

  /** One wall-clock tick of `tickS` seconds: plays the replay at its speed, as the hub's loop does. */
  run(tickS: number): void {
    if (!this.playing) return;
    this.step(tickS * this.speed);
    if (this.finished) {
      this.playing = false;
      this.broadcast(this.tick());
    }
  }

  private dispatch(insightId: string, v: StaticViewer): void {
    const row = this.rows.get(v.profile.profile_id)?.get(insightId);
    if (!row?.display) return;
    const insight = row.insight ?? this.b.insights[insightId];
    v.send({ type: "overlay", source: row.source, payload: { schema_version: "1.0", insight, rendered: row.rendered, display: row.display }, trace: row.trace });
  }

  private broadcast(msg: StreamMessage): void {
    for (const v of this.viewers) v.send(msg);
  }

  /** Elapsed time of the first event at or after a match minute (stoppage folds into 45 and 90). */
  elapsedForMinute(minute: number): number {
    const i = this.b.events.findIndex((e) => minuteOf(e.period, e.t) >= minute);
    return i < 0 ? this.b.end_s : this.b.elapsed[i];
  }

  private seek(elapsed: number): void {
    const backwards = elapsed < this.clockS;
    if (backwards) [this.cursor, this.firedIdx, this.clockS] = [0, 0, 0];
    this.advanceTo(elapsed); // skipped moments go to history, not to screens
    if (backwards) this.broadcast({ type: "reset" });
  }

  /** Apply a replay control, as Hub.control, and return the new status. */
  control(req: ControlRequest): ReplayStatus {
    const { action, value, minute } = req;
    if (action === "play") {
      if (this.finished) this.seek(0);
      this.playing = true;
    } else if (action === "pause") this.playing = false;
    else if (action === "speed") {
      if (value == null) throw new Error("speed needs a value");
      this.speed = Math.max(SPEED_MIN, Math.min(SPEED_MAX, value));
    } else if (action === "seek") this.seek(minute != null ? this.elapsedForMinute(minute) : (value ?? 0));
    else if (action === "step") this.step(value ?? 1);
    else if (action === "restart") this.seek(0);
    this.broadcast(this.tick());
    return this.status();
  }

  /** Register a viewer and send it hello and the current tick. */
  connect(v: StaticViewer): void {
    this.viewers.add(v);
    v.send({ type: "hello", match: this.b.match, profile: v.profile, replay: this.status() });
    v.send(this.tick());
  }

  /** Forget a viewer. */
  disconnect(v: StaticViewer): void {
    this.viewers.delete(v);
  }

  /** Every insight reached so far, as GET /api/insights. */
  insights(): Insight[] {
    return this.b.fired.slice(0, this.firedIdx).map(([, id]) => this.b.insights[id]);
  }

  /** Momentum samples up to the replay clock, as GET /api/momentum. */
  momentum(): MomentumPoint[] {
    return this.b.momentum.filter(([s]) => s <= this.clockS).map(([, minute, index]) => ({ minute, index }));
  }

  /** One insight rendered for a profile (or its closest precomputed one), as GET /api/render. */
  render(insightId: string, q: ProfileParams): RenderResponse {
    if (!this.insights().some((i) => i.insight_id === insightId)) throw new Error("404 insight not reached yet");
    const { profile } = resolveProfile(this.b, q);
    const row = this.rows.get(profile.profile_id)?.get(insightId);
    if (!row) throw new Error(`404 no rendering of ${insightId} for ${profile.profile_id}`);
    return { insight: row.insight ?? this.b.insights[insightId], rendered: row.rendered, trace: row.trace, source: row.source };
  }
}

let hub: Promise<StaticHub> | null = null;

/** The page's one hub, created when the bundle has loaded; its clock ticks every 100 ms of wall time. */
export function staticHub(): Promise<StaticHub> {
  hub ??= fetch(`${import.meta.env.BASE_URL}demo/bundle.json`)
    .then((r) => {
      if (!r.ok) throw new Error(`demo bundle: ${r.status}`);
      return r.json() as Promise<Bundle>;
    })
    .then((b) => {
      const h = new StaticHub(b);
      window.setInterval(() => h.run(0.1), 100);
      return h;
    });
  return hub;
}

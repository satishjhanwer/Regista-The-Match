/* Generated from contracts/schema by `npm run contracts`. Do not edit by hand. */

/**
 * Schema root that bundles the wire types for code generation. Never sent itself.
 */
export interface StreamContract {
  message: HelloMessage | TickMessage | EventsMessage | OverlayMessage | ResetMessage | ErrorMessage;
  render: RenderResponse;
  control: ControlRequest;
  status: ReplayStatus;
  momentum: MomentumPoint[];
}
export interface HelloMessage {
  type: "hello";
  match: MatchMeta;
  profile: FanProfile;
  replay: ReplayStatus;
}
export interface MatchMeta {
  schema_version: string;
  match_id: string;
  competition: string;
  venue: string;
  kickoff_utc: string;
  home: Team;
  away: Team;
  home_attacks_right_first_half: boolean;
  seed: number;
  generator: string;
}
export interface Team {
  team_id: string;
  name: string;
  short_name: string;
  primary_color: string;
  secondary_color: string;
  formation: string;
  players: Player[];
}
export interface Player {
  player_id: string;
  name: string;
  short_name: string;
  shirt: number;
  position: "GK" | "DEF" | "MID" | "FWD";
  /**
   * Tactical role in the formation, e.g. LCB, CDM, RW
   */
  role: string;
  /**
   * Appearances before this match
   */
  career_appearances: number;
  /**
   * Goals before this match
   */
  career_goals: number;
}
export interface FanProfile {
  profile_id: string;
  mode: "analyst" | "casual" | "player_focus";
  /**
   * BCP 47 tag, e.g. en, hi, es
   */
  language: string;
  favorite_team_id: string | null;
  focus_player_id: string | null;
  metric_of_interest: string | null;
}
export interface ReplayStatus {
  playing: boolean;
  /**
   * Match seconds per wall-clock second
   */
  speed: number;
  finished: boolean;
  clock: StreamClock;
  viewers: number;
}
export interface StreamClock {
  period: 1 | 2;
  t: number;
  match_clock_s: number;
  elapsed_s: number;
  display: string;
}
export interface TickMessage {
  type: "tick";
  clock: StreamClock;
  score: {
    [k: string]: number;
  };
  playing: boolean;
  speed: number;
  metrics: LiveMetrics;
}
export interface LiveMetrics {
  /**
   * Home-positive momentum index in [-1, 1]
   */
  momentum_index: number;
  /**
   * Team id -> share of momentum, 0..1
   */
  momentum: {
    [k: string]: number;
  };
  /**
   * Match chaos index over 5 min, 0 calm .. 1 chaotic
   */
  chaos: number | null;
  /**
   * Team id -> control score over 5 min, 0..1
   */
  control: {
    [k: string]: number;
  };
  xg: {
    [k: string]: number;
  };
  /**
   * Pressing team id -> share of opponent passes under pressure (5 min)
   */
  pressed_share: {
    [k: string]: number;
  };
  press_cusum: {
    [k: string]: number;
  };
}
export interface EventsMessage {
  type: "events";
  events: StreamEvent[];
}
/**
 * A match event compacted for the pitch view (absolute pitch metres).
 */
export interface StreamEvent {
  id: string;
  type: string;
  period: 1 | 2;
  t: number;
  team: string | null;
  player: string | null;
  x: number;
  y: number;
  end_x: number | null;
  end_y: number | null;
  outcome: string | null;
  height: string | null;
  is_cross: boolean;
  is_through_ball: boolean;
  top_speed_kmh: number | null;
  shot_speed_kmh: number | null;
  cause: string | null;
}
export interface OverlayMessage {
  type: "overlay";
  source: "llm" | "llm_revised" | "template" | "template_fallback" | "cache";
  payload: OverlayPayload;
  trace: TraceStep[];
}
export interface OverlayPayload {
  schema_version: string;
  insight: Insight;
  rendered: RenderedInsight;
  display: DisplayDirective;
}
export interface Insight {
  insight_id: string;
  match_id: string;
  kind:
    | "goal"
    | "momentum_shift"
    | "press_change"
    | "control_vs_chaos"
    | "rhythm_shift"
    | "shot_quality"
    | "key_pass"
    | "player_tag"
    | "milestone"
    | "period_summary"
    | "recap";
  /**
   * 5 = interrupt-worthy
   */
  priority: number;
  clock: MatchClock;
  created_at: string;
  ttl_ms: number;
  entities: Entities;
  facts: Fact[];
  /**
   * Deterministic detector rationale handed to the agents, never shown verbatim
   */
  why_it_matters_hint: string;
}
export interface MatchClock {
  period: 1 | 2;
  t: number;
  match_clock_s: number;
  display: string;
}
export interface Entities {
  team_ids: string[];
  player_ids: string[];
}
export interface Fact {
  fact_id: string;
  /**
   * Stable machine key, e.g. 'home.pass_completion_own_half'
   */
  key: string;
  /**
   * Human label in English; renderers localize
   */
  label: string;
  value: number | string;
  unit: string | null;
  /**
   * Baseline the value is compared against, for deltas
   */
  previous_value: number | string | null;
  evidence: EvidenceRef[];
}
export interface EvidenceRef {
  kind: "event" | "metric";
  /**
   * event_id for events, metric key (e.g. 'away.ppda') for metrics
   */
  ref: string;
  window_start_s: number | null;
  window_end_s: number | null;
}
export interface RenderedInsight {
  insight_id: string;
  profile_id: string;
  language: string;
  mode: "analyst" | "casual" | "player_focus";
  headline: string;
  body: string;
  stat_callout: StatCallout | null;
  claims: Claim[];
  verification: Verification;
}
export interface StatCallout {
  label: string;
  value: string;
  fact_id: string;
}
export interface Claim {
  text: string;
  /**
   * Facts this sentence relies on; empty means opinion/colour only
   */
  fact_ids: string[];
}
export interface Verification {
  status: "pending" | "verified" | "revised" | "rejected";
  checked_claims: number;
  rejected_claims: number;
  notes: string[];
}
export interface DisplayDirective {
  slot: "lower_third" | "top_bar" | "side_panel" | "ticker" | "player_tag";
  template_id: string;
  show_at_match_clock_s: number;
  ttl_ms: number;
  priority: number;
}
export interface TraceStep {
  agent: "analyst" | "narrator" | "verifier" | "template" | "cache";
  action: string;
  status: "ok" | "rejected" | "error" | "fallback";
  ms: number;
  detail: {
    [k: string]: unknown;
  };
}
export interface ResetMessage {
  type: "reset";
}
export interface ErrorMessage {
  type: "error";
  error: string;
}
/**
 * GET /api/render/{insight_id}.
 */
export interface RenderResponse {
  insight: Insight;
  rendered: RenderedInsight;
  trace: TraceStep[];
  source: "llm" | "llm_revised" | "template" | "template_fallback" | "cache";
}
/**
 * POST /api/replay, or {"type": "control", ...} on the socket.
 */
export interface ControlRequest {
  action: "play" | "pause" | "speed" | "seek" | "step" | "restart";
  value: number | null;
  minute: number | null;
}
export interface MomentumPoint {
  /**
   * Football minute (stoppage folded into 45 / 90)
   */
  minute: number;
  /**
   * Home-positive momentum index in [-1, 1]
   */
  index: number;
}

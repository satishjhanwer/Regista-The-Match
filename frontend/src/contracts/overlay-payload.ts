/* Generated from contracts/schema by `npm run contracts`. Do not edit by hand. */

/**
 * What goes over the wire to the overlay: the insight, its rendering and where to show it.
 */
export interface OverlayPayload {
  schema_version: string;
  insight: Insight;
  rendered: RenderedInsight;
  display: DisplayDirective;
}
/**
 * A detected moment: one canonical set of facts that every rendering must stay within.
 */
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
/**
 * When a moment happened, with its broadcast display string.
 */
export interface MatchClock {
  period: 1 | 2;
  t: number;
  match_clock_s: number;
  display: string;
}
/**
 * Teams and players an insight is about.
 */
export interface Entities {
  team_ids: string[];
  player_ids: string[];
}
/**
 * One number or value with its label, optional baseline and evidence. The unit of truth.
 */
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
/**
 * What a fact rests on: an event id, or a metric key with its time window (elapsed seconds).
 */
export interface EvidenceRef {
  kind: "event" | "metric";
  /**
   * event_id for events, metric key (e.g. 'away.ppda') for metrics
   */
  ref: string;
  window_start_s: number | null;
  window_end_s: number | null;
}
/**
 * An insight told for one fan profile.
 */
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
/**
 * The one stat a graphic highlights.
 */
export interface StatCallout {
  label: string;
  value: string;
  fact_id: string;
}
/**
 * One sentence and the facts it relies on.
 */
export interface Claim {
  text: string;
  /**
   * Facts this sentence relies on; empty means opinion/colour only
   */
  fact_ids: string[];
}
/**
 * The Verifier's verdict on a rendering.
 */
export interface Verification {
  status: "pending" | "verified" | "revised" | "rejected";
  checked_claims: number;
  rejected_claims: number;
  notes: string[];
}
/**
 * Where and when a graphic airs, and for how long.
 */
export interface DisplayDirective {
  slot: "lower_third" | "top_bar" | "side_panel" | "ticker" | "player_tag";
  template_id: string;
  show_at_match_clock_s: number;
  ttl_ms: number;
  priority: number;
}

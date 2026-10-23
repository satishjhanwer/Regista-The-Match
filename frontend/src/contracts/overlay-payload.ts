/* Generated from contracts/schema by `npm run contracts`. Do not edit by hand. */

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

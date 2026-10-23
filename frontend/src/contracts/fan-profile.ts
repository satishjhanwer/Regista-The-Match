/* Generated from contracts/schema by `npm run contracts`. Do not edit by hand. */

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

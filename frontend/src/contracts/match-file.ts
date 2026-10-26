/* Generated from contracts/schema by `npm run contracts`. Do not edit by hand. */

/**
 * A full simulated match: metadata plus the ordered event stream.
 */
export interface MatchFile {
  meta: MatchMeta;
  events: (
    | PeriodStartEvent
    | PeriodEndEvent
    | PassEvent
    | CarryEvent
    | ShotEvent
    | SaveEvent
    | PressureEvent
    | TackleEvent
    | InterceptionEvent
    | ClearanceEvent
    | FoulEvent
    | SprintEvent
    | PossessionChangeEvent
  )[];
}
/**
 * Match metadata: teams, venue, kickoff and which way the home side attacks first.
 */
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
/**
 * A club and its eleven.
 */
export interface Team {
  team_id: string;
  name: string;
  short_name: string;
  primary_color: string;
  secondary_color: string;
  formation: string;
  players: Player[];
}
/**
 * A squad member, with career totals before this match.
 */
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
/**
 * Kickoff of a period.
 */
export interface PeriodStartEvent {
  event_id: string;
  seq: number;
  match_id: string;
  period: 1 | 2;
  /**
   * Seconds since period start
   */
  t: number;
  /**
   * Broadcast clock; period 2 restarts at 2700 so it can overlap 1st-half stoppage
   */
  match_clock_s: number;
  /**
   * Monotonic playing time since kickoff incl. stoppage; use for replay ordering
   */
  elapsed_s: number;
  team_id: string | null;
  player_id: string | null;
  possession_id: number;
  x: number;
  y: number;
  type: "period_start";
}
/**
 * End of a period, with the score.
 */
export interface PeriodEndEvent {
  event_id: string;
  seq: number;
  match_id: string;
  period: 1 | 2;
  /**
   * Seconds since period start
   */
  t: number;
  /**
   * Broadcast clock; period 2 restarts at 2700 so it can overlap 1st-half stoppage
   */
  match_clock_s: number;
  /**
   * Monotonic playing time since kickoff incl. stoppage; use for replay ordering
   */
  elapsed_s: number;
  team_id: string | null;
  player_id: string | null;
  possession_id: number;
  x: number;
  y: number;
  type: "period_end";
  home_score: number;
  away_score: number;
}
/**
 * A pass with its outcome, length, height, ball speed and the pressure on passer and receiver.
 */
export interface PassEvent {
  event_id: string;
  seq: number;
  match_id: string;
  period: 1 | 2;
  /**
   * Seconds since period start
   */
  t: number;
  /**
   * Broadcast clock; period 2 restarts at 2700 so it can overlap 1st-half stoppage
   */
  match_clock_s: number;
  /**
   * Monotonic playing time since kickoff incl. stoppage; use for replay ordering
   */
  elapsed_s: number;
  team_id: string | null;
  player_id: string | null;
  possession_id: number;
  x: number;
  y: number;
  type: "pass";
  end_x: number;
  end_y: number;
  recipient_id: string | null;
  outcome: "complete" | "incomplete" | "out";
  length_m: number;
  height: "ground" | "low" | "high";
  duration_s: number;
  /**
   * Mean ball speed over the pass
   */
  ball_speed_kmh: number;
  pressure: Pressure;
  receiver_defenders_within_5m: number;
  is_cross: boolean;
  is_through_ball: boolean;
}
/**
 * Opponents around a player at the moment of an action.
 */
export interface Pressure {
  defenders_within_5m: number;
  nearest_defender_m: number;
  nearest_defender_id: string | null;
}
/**
 * A player running with the ball.
 */
export interface CarryEvent {
  event_id: string;
  seq: number;
  match_id: string;
  period: 1 | 2;
  /**
   * Seconds since period start
   */
  t: number;
  /**
   * Broadcast clock; period 2 restarts at 2700 so it can overlap 1st-half stoppage
   */
  match_clock_s: number;
  /**
   * Monotonic playing time since kickoff incl. stoppage; use for replay ordering
   */
  elapsed_s: number;
  team_id: string | null;
  player_id: string | null;
  possession_id: number;
  x: number;
  y: number;
  type: "carry";
  end_x: number;
  end_y: number;
  distance_m: number;
  duration_s: number;
  top_speed_kmh: number;
}
/**
 * A shot with outcome, body part, speed, goal geometry, pressure, assist and freeze frame.
 */
export interface ShotEvent {
  event_id: string;
  seq: number;
  match_id: string;
  period: 1 | 2;
  /**
   * Seconds since period start
   */
  t: number;
  /**
   * Broadcast clock; period 2 restarts at 2700 so it can overlap 1st-half stoppage
   */
  match_clock_s: number;
  /**
   * Monotonic playing time since kickoff incl. stoppage; use for replay ordering
   */
  elapsed_s: number;
  team_id: string | null;
  player_id: string | null;
  possession_id: number;
  x: number;
  y: number;
  type: "shot";
  outcome: "goal" | "saved" | "off_target" | "blocked" | "woodwork";
  body_part: "right_foot" | "left_foot" | "head";
  shot_speed_kmh: number;
  /**
   * Distance to centre of goal
   */
  distance_m: number;
  /**
   * Angle subtended by the goal mouth
   */
  angle_rad: number;
  pressure: Pressure;
  assist_event_id: string | null;
  freeze_frame: FreezeFramePlayer[];
}
/**
 * A player's position in a shot's freeze frame.
 */
export interface FreezeFramePlayer {
  player_id: string;
  x: number;
  y: number;
}
/**
 * A goalkeeper save.
 */
export interface SaveEvent {
  event_id: string;
  seq: number;
  match_id: string;
  period: 1 | 2;
  /**
   * Seconds since period start
   */
  t: number;
  /**
   * Broadcast clock; period 2 restarts at 2700 so it can overlap 1st-half stoppage
   */
  match_clock_s: number;
  /**
   * Monotonic playing time since kickoff incl. stoppage; use for replay ordering
   */
  elapsed_s: number;
  team_id: string | null;
  player_id: string | null;
  possession_id: number;
  x: number;
  y: number;
  type: "save";
  shot_event_id: string;
}
/**
 * A defender closing down the ball carrier.
 */
export interface PressureEvent {
  event_id: string;
  seq: number;
  match_id: string;
  period: 1 | 2;
  /**
   * Seconds since period start
   */
  t: number;
  /**
   * Broadcast clock; period 2 restarts at 2700 so it can overlap 1st-half stoppage
   */
  match_clock_s: number;
  /**
   * Monotonic playing time since kickoff incl. stoppage; use for replay ordering
   */
  elapsed_s: number;
  team_id: string | null;
  player_id: string | null;
  possession_id: number;
  x: number;
  y: number;
  type: "pressure";
  target_player_id: string;
  distance_m: number;
  duration_s: number;
}
/**
 * A tackle.
 */
export interface TackleEvent {
  event_id: string;
  seq: number;
  match_id: string;
  period: 1 | 2;
  /**
   * Seconds since period start
   */
  t: number;
  /**
   * Broadcast clock; period 2 restarts at 2700 so it can overlap 1st-half stoppage
   */
  match_clock_s: number;
  /**
   * Monotonic playing time since kickoff incl. stoppage; use for replay ordering
   */
  elapsed_s: number;
  team_id: string | null;
  player_id: string | null;
  possession_id: number;
  x: number;
  y: number;
  type: "tackle";
  opponent_id: string;
  outcome: "won" | "lost";
}
/**
 * An intercepted pass.
 */
export interface InterceptionEvent {
  event_id: string;
  seq: number;
  match_id: string;
  period: 1 | 2;
  /**
   * Seconds since period start
   */
  t: number;
  /**
   * Broadcast clock; period 2 restarts at 2700 so it can overlap 1st-half stoppage
   */
  match_clock_s: number;
  /**
   * Monotonic playing time since kickoff incl. stoppage; use for replay ordering
   */
  elapsed_s: number;
  team_id: string | null;
  player_id: string | null;
  possession_id: number;
  x: number;
  y: number;
  type: "interception";
  pass_event_id: string;
}
/**
 * A defensive clearance.
 */
export interface ClearanceEvent {
  event_id: string;
  seq: number;
  match_id: string;
  period: 1 | 2;
  /**
   * Seconds since period start
   */
  t: number;
  /**
   * Broadcast clock; period 2 restarts at 2700 so it can overlap 1st-half stoppage
   */
  match_clock_s: number;
  /**
   * Monotonic playing time since kickoff incl. stoppage; use for replay ordering
   */
  elapsed_s: number;
  team_id: string | null;
  player_id: string | null;
  possession_id: number;
  x: number;
  y: number;
  type: "clearance";
  end_x: number;
  end_y: number;
}
/**
 * A foul, with any card.
 */
export interface FoulEvent {
  event_id: string;
  seq: number;
  match_id: string;
  period: 1 | 2;
  /**
   * Seconds since period start
   */
  t: number;
  /**
   * Broadcast clock; period 2 restarts at 2700 so it can overlap 1st-half stoppage
   */
  match_clock_s: number;
  /**
   * Monotonic playing time since kickoff incl. stoppage; use for replay ordering
   */
  elapsed_s: number;
  team_id: string | null;
  player_id: string | null;
  possession_id: number;
  x: number;
  y: number;
  type: "foul";
  fouled_player_id: string;
  card: ("yellow" | "red") | null;
}
/**
 * Physical-tracking derived event: a player's run with peak speed and distance.
 */
export interface SprintEvent {
  event_id: string;
  seq: number;
  match_id: string;
  period: 1 | 2;
  /**
   * Seconds since period start
   */
  t: number;
  /**
   * Broadcast clock; period 2 restarts at 2700 so it can overlap 1st-half stoppage
   */
  match_clock_s: number;
  /**
   * Monotonic playing time since kickoff incl. stoppage; use for replay ordering
   */
  elapsed_s: number;
  team_id: string | null;
  player_id: string | null;
  possession_id: number;
  x: number;
  y: number;
  type: "sprint";
  top_speed_kmh: number;
  distance_m: number;
  duration_s: number;
}
/**
 * The ball changes team, and why.
 */
export interface PossessionChangeEvent {
  event_id: string;
  seq: number;
  match_id: string;
  period: 1 | 2;
  /**
   * Seconds since period start
   */
  t: number;
  /**
   * Broadcast clock; period 2 restarts at 2700 so it can overlap 1st-half stoppage
   */
  match_clock_s: number;
  /**
   * Monotonic playing time since kickoff incl. stoppage; use for replay ordering
   */
  elapsed_s: number;
  team_id: string | null;
  player_id: string | null;
  possession_id: number;
  x: number;
  y: number;
  type: "possession_change";
  from_team_id: string | null;
  to_team_id: string;
  cause: "kickoff" | "tackle" | "interception" | "out_of_play" | "save" | "clearance" | "foul" | "goal_kick";
}

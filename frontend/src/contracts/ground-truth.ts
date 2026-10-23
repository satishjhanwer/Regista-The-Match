/* Generated from contracts/schema by `npm run contracts`. Do not edit by hand. */

export interface GroundTruth {
  match_id: string;
  seed: number;
  final_score: {
    [k: string]: number;
  };
  storylines: Storyline[];
  scripted_event_ids: {
    [k: string]: string;
  };
  shots: TruthShot[];
  pass_model: {
    [k: string]: number;
  };
  xg_model: {
    [k: string]: number;
  };
}
export interface Storyline {
  storyline_id: string;
  label: string;
  start_clock_s: number;
  end_clock_s: number;
  description: string;
  expected_signals: string[];
}
export interface TruthShot {
  event_id: string;
  xg_true: number;
}

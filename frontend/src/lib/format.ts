import type { Fact, MatchMeta, Team } from "../contracts/stream";

/** Lighten a hex colour towards white, so dark kit colours read on the dark pitch. */
export function lighten(hex: string, amount = 0.45): string {
  const n = parseInt(hex.slice(1), 16);
  const mix = (c: number) => Math.round(c + (255 - c) * amount);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(mix);
  return `rgb(${r}, ${g}, ${b})`;
}

/** Per-team colours: `ink` for drawing on the dark pitch, `kit` for the score bug. */
export interface Palette {
  ink: Record<string, string>;
  kit: Record<string, string>;
}

/** Team colours derived from the match metadata. */
export function palette(meta: MatchMeta | null): Palette {
  if (!meta) return { ink: {}, kit: {} };
  const teams: Team[] = [meta.home, meta.away];
  return {
    ink: Object.fromEntries(teams.map((t) => [t.team_id, lighten(t.primary_color)])),
    kit: Object.fromEntries(teams.map((t) => [t.team_id, t.primary_color])),
  };
}

/** Player id to short name, for labels. */
export function playerNames(meta: MatchMeta | null): Record<string, string> {
  if (!meta) return {};
  return Object.fromEntries([...meta.home.players, ...meta.away.players].map((p) => [p.player_id, p.short_name]));
}

/** A fact's value with its unit, as shown in chips and lists. */
export function factText(f: Fact): string {
  const unit = f.unit === null ? "" : f.unit === "%" ? "%" : ` ${f.unit}`;
  return `${f.value}${unit}`;
}

/** Elapsed seconds as m:ss (evidence windows are on the monotonic elapsed clock). */
export function elapsedText(s: number | null): string {
  if (s === null) return "";
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

/** Display label per insight kind. */
export const KIND_LABEL: Record<string, string> = {
  goal: "Goal",
  shot_quality: "Big chance",
  key_pass: "Key pass",
  momentum_shift: "Momentum",
  press_change: "Press change",
  control_vs_chaos: "Control vs chaos",
  rhythm_shift: "Rhythm",
  player_tag: "Player tag",
  milestone: "Milestone",
  period_summary: "Summary",
  recap: "Recap",
};

/** Languages a fan can choose. */
export const LANGS = [
  { code: "en", label: "English" },
  { code: "es", label: "Español" },
  { code: "hi", label: "हिन्दी" },
];

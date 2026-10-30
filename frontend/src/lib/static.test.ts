import { describe, expect, it } from "vitest";

import type { FanProfile, Insight, LiveMetrics, StreamEvent } from "../contracts/stream";
import type { StreamMessage } from "./live";
import { formatClock, resolveProfile, StaticHub, type Bundle, type RenderRow } from "./static";

const metrics = (i: number): LiveMetrics => ({ momentum_index: i, momentum: {}, chaos: null, control: {}, xg: {}, pressed_share: {}, press_cusum: {} });
const profile = (id: string, mode: FanProfile["mode"], language: string, team: string | null = null, player: string | null = null): FanProfile => ({
  profile_id: id,
  mode,
  language,
  favorite_team_id: team,
  focus_player_id: player,
  metric_of_interest: null,
});
const event = (id: string, period: 1 | 2, t: number, type = "pass"): StreamEvent => ({ id, type, period, t, team: "NVL", player: "NVL-09", x: 50, y: 34 }) as StreamEvent;
const insight = (id: string): Insight => ({ insight_id: id, kind: "goal", facts: [], entities: { team_ids: ["NVL"], player_ids: [] } }) as unknown as Insight;
const row = (id: string, shown: boolean): RenderRow =>
  ({ id, source: "template", rendered: { headline: id }, display: shown ? { slot: "lower_third" } : null, trace: [] }) as unknown as RenderRow;

const analyst = profile("analyst-en", "analyst", "en");
const casualNvl = profile("casual-en-NVL-_-_", "casual", "en", "NVL");
const bundle: Bundle = {
  version: 1,
  match: { home: { team_id: "NVL" }, away: { team_id: "SLM" } } as Bundle["match"],
  presets: [analyst],
  profiles: [analyst, casualNvl],
  end_s: 3000,
  events: [event("e1", 1, 0, "period_start"), event("e2", 1, 60), event("e3", 1, 600), event("e4", 1, 2760, "period_end"), event("e5", 2, 0, "period_start")],
  elapsed: [0, 60, 600, 2760, 2900],
  match_clock: [0, 60, 600, 2760, 2700],
  ticks: [0, 1, 2, 3, 4].map((i) => ({ score: { NVL: i >= 2 ? 1 : 0, SLM: 0 }, metrics: metrics(i / 10) })),
  momentum: [
    [60, 1, 0.1],
    [600, 10, 0.2],
  ],
  insights: { G1: insight("G1"), M1: insight("M1") },
  fired: [
    [600, "G1"],
    [600, "M1"],
  ],
  renders: { "analyst-en": [row("G1", true), row("M1", false)], "casual-en-NVL-_-_": [row("G1", true), row("M1", true)] },
  recorded_from: null,
};

function viewer(hub: StaticHub, p: FanProfile) {
  const got: StreamMessage[] = [];
  hub.connect({ profile: p, send: (m) => got.push(m) });
  return got;
}

describe("static hub", () => {
  it("formats the clock like the backend", () => {
    expect(formatClock(1, 1421)).toBe("23:41");
    expect(formatClock(2, 1325)).toBe("67:05");
    expect(formatClock(1, 2772)).toBe("45+01:12");
    expect(formatClock(2, 2900)).toBe("90+03:20");
  });

  it("plays the replay and sends each viewer only the overlays it would see", () => {
    const hub = new StaticHub(bundle, false);
    const a = viewer(hub, analyst);
    const c = viewer(hub, casualNvl);
    expect(a[0].type).toBe("hello");
    hub.control({ action: "speed", value: 60, minute: null });
    hub.control({ action: "play", value: null, minute: null });
    for (let i = 0; i < 11; i++) hub.run(1); // 660 match seconds
    const overlays = (got: StreamMessage[]) => got.filter((m) => m.type === "overlay").map((m) => (m.type === "overlay" ? m.payload.insight.insight_id : ""));
    expect(overlays(a)).toEqual(["G1"]);
    expect(overlays(c)).toEqual(["G1", "M1"]);
    const tick = hub.tick();
    expect(tick.score).toEqual({ NVL: 1, SLM: 0 });
    expect(tick.clock.display).toBe("11:00");
    expect(hub.insights().map((i) => i.insight_id)).toEqual(["G1", "M1"]);
    expect(hub.momentum()).toEqual([
      { minute: 1, index: 0.1 },
      { minute: 10, index: 0.2 },
    ]);
  });

  it("seeks like the hub: skipped moments are history, going back resets screens", () => {
    const hub = new StaticHub(bundle, false);
    const a = viewer(hub, analyst);
    hub.control({ action: "seek", value: null, minute: 20 });
    expect(a.some((m) => m.type === "overlay")).toBe(false);
    expect(hub.insights()).toHaveLength(2);
    hub.control({ action: "seek", value: null, minute: 0.5 }); // lands on the 1:00 event, before the goal
    expect(a.some((m) => m.type === "reset")).toBe(true);
    expect(hub.insights()).toHaveLength(0);
    expect(() => hub.render("G1", { profile: "analyst-en" })).toThrow(/not reached/);
  });

  it("stops at the end, and play restarts a finished replay", () => {
    const hub = new StaticHub(bundle, true);
    hub.control({ action: "speed", value: 120, minute: null });
    for (let i = 0; i < 40 && !hub.finished; i++) hub.run(1);
    expect(hub.finished).toBe(true);
    hub.run(1);
    expect(hub.playing).toBe(false);
    hub.control({ action: "play", value: null, minute: null });
    expect(hub.cursor).toBe(1);
    expect(hub.playing).toBe(true);
    expect(hub.control({ action: "speed", value: 1000, minute: null }).speed).toBe(120);
  });

  it("serves the closest precomputed profile", () => {
    expect(resolveProfile(bundle, { profile: "analyst-en" })).toEqual({ profile: analyst, exact: true });
    expect(resolveProfile(bundle, { mode: "casual", lang: "en", team: "NVL", player: "", metric: "" })).toEqual({ profile: casualNvl, exact: true });
    expect(resolveProfile(bundle, { mode: "casual", lang: "en", team: "SLM", player: "", metric: "" })).toEqual({ profile: casualNvl, exact: false });
    expect(resolveProfile(bundle, { mode: "player_focus", lang: "hi" }).profile).toBe(analyst);
  });
});

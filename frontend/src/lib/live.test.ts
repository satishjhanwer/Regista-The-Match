import { describe, expect, it } from "vitest";

import type { TickMessage } from "../contracts/stream";
import { initialLive, matchMinute, needsHistory, reduce } from "./live";

function tickAt(period: 1 | 2, t: number, index = 0.2): TickMessage {
  return {
    type: "tick",
    clock: { period, t, match_clock_s: t + (period === 2 ? 2700 : 0), elapsed_s: t, display: "" },
    score: { NVL: 0, SLM: 0 },
    playing: true,
    speed: 10,
    metrics: { momentum_index: index, momentum: {}, chaos: null, control: {}, xg: {}, pressed_share: {}, press_cusum: {} },
  };
}

describe("live reducer", () => {
  it("folds stoppage into the last minute of each half", () => {
    expect(matchMinute(1, 2800)).toBeCloseTo(44.9998, 3);
    expect(matchMinute(2, 60)).toBe(46);
  });

  it("samples momentum and marks a gap after a seek", () => {
    let s = reduce(initialLive, tickAt(1, 600));
    s = reduce(s, tickAt(1, 606));
    s = reduce(s, tickAt(1, 620));
    s = reduce(s, tickAt(1, 2000));
    expect(s.momentum.map((p) => p.gap)).toEqual([true, false, true]);
  });

  it("records goal markers from events and clears on reset", () => {
    let s = reduce(initialLive, {
      type: "events",
      events: [{ id: "e1", type: "shot", period: 1, t: 2292, team: "NVL", player: "NVL-09", x: 95, y: 33, end_x: null, end_y: null, outcome: "goal", height: null, is_cross: false, is_through_ball: false, top_speed_kmh: null, shot_speed_kmh: 100, cause: null }],
    });
    expect(s.markers).toHaveLength(1);
    expect(s.markers[0].kind).toBe("goal");
    s = reduce(s, { type: "reset" });
    expect(s.markers).toHaveLength(0);
    expect(s.resets).toBe(1);
  });
});

describe("history backfill", () => {
  it("replaces the ribbon with server history and asks again only after a jump", () => {
    let s = reduce(initialLive, {
      type: "history",
      momentum: [
        { minute: 0, index: 0 },
        { minute: 0.25, index: 0.5 },
        { minute: 30, index: -0.2 },
      ],
      insights: [],
    });
    expect(s.momentum).toHaveLength(3);
    expect(needsHistory(s, tickAt(1, 1810))).toBe(false);
    expect(needsHistory(s, tickAt(2, 600))).toBe(true);
    s = reduce(s, tickAt(1, 1815));
    expect(s.momentum[s.momentum.length - 1].gap).toBe(false);
  });
});

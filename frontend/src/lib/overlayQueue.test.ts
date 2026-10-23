import { describe, expect, it } from "vitest";

import type { OverlayMessage } from "../contracts/stream";
import { emptyQueue, enqueue, MAX_WAIT_MS, tick, type Slot } from "./overlayQueue";

function overlay(id: string, slot: Slot, priority: number, ttl = 8000, showAt = 0): OverlayMessage {
  return {
    type: "overlay",
    source: "template",
    trace: [],
    payload: {
      schema_version: "1.0",
      display: { slot, template_id: "t", show_at_match_clock_s: showAt, ttl_ms: ttl, priority },
      insight: { insight_id: id } as OverlayMessage["payload"]["insight"],
      rendered: { profile_id: "p" } as OverlayMessage["payload"]["rendered"],
    },
  };
}

describe("overlay queue", () => {
  it("airs a graphic and expires it after its TTL", () => {
    let q = enqueue(emptyQueue(), overlay("a", "lower_third", 3, 5000), 0);
    q = tick(q, 0, 100);
    expect(q.onAir.lower_third?.key).toBe("a/p");
    q = tick(q, 4999, 100);
    expect(q.onAir.lower_third?.key).toBe("a/p");
    q = tick(q, 5000, 100);
    expect(q.onAir.lower_third).toBeUndefined();
  });

  it("lets a higher priority preempt and requeues the rest of the preempted one", () => {
    let q = tick(enqueue(emptyQueue(), overlay("low", "lower_third", 2, 10000), 0), 0, 0);
    q = tick(enqueue(q, overlay("goal", "lower_third", 5, 4000), 1000), 1000, 0);
    expect(q.onAir.lower_third?.key).toBe("goal/p");
    q = tick(q, 5000, 0);
    expect(q.onAir.lower_third?.key).toBe("low/p");
    expect(q.onAir.lower_third?.remainingMs).toBe(9000);
  });

  it("queues equal priority behind the graphic on air", () => {
    let q = tick(enqueue(emptyQueue(), overlay("a", "side_panel", 3, 3000), 0), 0, 0);
    q = tick(enqueue(q, overlay("b", "side_panel", 3, 3000), 10), 10, 0);
    expect(q.onAir.side_panel?.key).toBe("a/p");
    q = tick(q, 3000, 0);
    expect(q.onAir.side_panel?.key).toBe("b/p");
  });

  it("keeps slots independent, dedupes, and drops stale waiting graphics", () => {
    let q = enqueue(emptyQueue(), overlay("a", "ticker", 3), 0);
    q = enqueue(q, overlay("a", "ticker", 3), 0);
    q = enqueue(q, overlay("b", "player_tag", 3), 0);
    q = tick(q, 0, 0);
    expect(Object.keys(q.onAir).sort()).toEqual(["player_tag", "ticker"]);
    q = enqueue(q, overlay("late", "ticker", 3, 8000), 1);
    q = tick(q, MAX_WAIT_MS + 2, 0);
    expect(q.waiting.find((w) => w.key === "late/p")).toBeUndefined();
  });

  it("never airs before the match clock reaches show_at", () => {
    let q = enqueue(emptyQueue(), overlay("a", "top_bar", 3, 5000, 600), 0);
    expect(tick(q, 0, 599).onAir.top_bar).toBeUndefined();
    q = tick(q, 10, 600);
    expect(q.onAir.top_bar?.key).toBe("a/p");
  });
});

// Overlay scheduling, as a broadcast graphics engine would do it.
//
// One graphic per slot. A higher-priority graphic preempts the one on air, and the
// preempted one goes back to the queue with its remaining time. Others wait in the
// queue (priority first, then arrival) and are dropped if they waited too long,
// because the moment has passed. A graphic never airs before its show_at match clock.
// Time is "air time" in ms. The caller advances it only while the replay plays, so a
// paused replay holds its graphics on screen.

import type { DisplayDirective, OverlayMessage } from "../contracts/stream";

export type Slot = DisplayDirective["slot"];
export const SLOTS: Slot[] = ["top_bar", "lower_third", "side_panel", "ticker", "player_tag"];

export interface Queued {
  key: string; // insight_id + profile
  msg: OverlayMessage;
  priority: number;
  slot: Slot;
  showAtClock: number; // match_clock_s
  arrivedAt: number; // air ms
  remainingMs: number;
}

export interface OnAir extends Queued {
  startedAt: number;
}

export interface QueueState {
  onAir: Partial<Record<Slot, OnAir>>;
  waiting: Queued[];
  seen: Set<string>;
}

export const MAX_WAIT_MS = 12_000;

export function emptyQueue(): QueueState {
  return { onAir: {}, waiting: [], seen: new Set() };
}

export function enqueue(state: QueueState, msg: OverlayMessage, airNow: number): QueueState {
  const key = `${msg.payload.insight.insight_id}/${msg.payload.rendered.profile_id}`;
  if (state.seen.has(key)) return state;
  const d = msg.payload.display;
  const item: Queued = {
    key,
    msg,
    priority: d.priority,
    slot: d.slot,
    showAtClock: d.show_at_match_clock_s,
    arrivedAt: airNow,
    remainingMs: d.ttl_ms,
  };
  const seen = new Set(state.seen).add(key);
  return { onAir: state.onAir, waiting: [...state.waiting, item], seen };
}

function better(a: Queued, b: Queued): number {
  return b.priority - a.priority || a.arrivedAt - b.arrivedAt;
}

/** Advance to air time `airNow` at match clock `matchClock`: expire, preempt, promote. */
export function tick(state: QueueState, airNow: number, matchClock: number): QueueState {
  const onAir: Partial<Record<Slot, OnAir>> = {};
  let waiting = state.waiting.filter((q) => airNow - q.arrivedAt <= MAX_WAIT_MS || q.remainingMs < q.msg.payload.display.ttl_ms);

  for (const slot of SLOTS) {
    let current = state.onAir[slot];
    if (current && airNow - current.startedAt >= current.remainingMs) current = undefined;
    const ready = waiting.filter((q) => q.slot === slot && q.showAtClock <= matchClock + 1e-6).sort(better);
    const best = ready[0];
    if (best && (!current || best.priority > current.priority)) {
      if (current) {
        // preempted: back to the queue with what is left of its time
        const left = current.remainingMs - (airNow - current.startedAt);
        if (left > 1500) waiting = [...waiting, { ...current, remainingMs: left, arrivedAt: airNow }];
      }
      waiting = waiting.filter((q) => q !== best);
      current = { ...best, startedAt: airNow };
    }
    if (current) onAir[slot] = current;
  }
  return { onAir, waiting, seen: state.seen };
}

/** Fraction of on-air time used, for progress bars. */
export function progress(item: OnAir, airNow: number): number {
  return Math.min(1, Math.max(0, (airNow - item.startedAt) / item.remainingMs));
}

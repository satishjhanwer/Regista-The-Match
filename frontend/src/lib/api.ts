/**
 * REST helpers and the WebSocket hook for the Regista replay API (see docs/API.md).
 */

import { useEffect, useReducer, useRef } from "react";

import type { ControlRequest, FanProfile, Insight, MomentumPoint, RenderResponse, ReplayStatus } from "../contracts/stream";
import { initialLive, needsHistory, reduce, type LiveState, type StreamMessage } from "./live";

/** Fan profile as query parameters: a preset id, optionally overridden field by field. */
export interface ProfileParams {
  profile?: string;
  mode?: FanProfile["mode"];
  lang?: string;
  team?: string;
  player?: string;
  metric?: string;
}

/** URL query string for a profile (undefined fields are left out). */
export function profileQuery(p: ProfileParams): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (v !== undefined) q.set(k, v);
  return q.toString();
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return (await res.json()) as T;
}

/** Typed REST calls to the replay API. */
export const api = {
  control: (body: ControlRequest) =>
    fetch("/api/replay", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }).then(json<ReplayStatus>),
  profiles: () => fetch("/api/profiles").then(json<FanProfile[]>),
  insights: () => fetch("/api/insights").then(json<Insight[]>),
  momentum: () => fetch("/api/momentum").then(json<MomentumPoint[]>),
  render: (insightId: string, p: ProfileParams) => fetch(`/api/render/${encodeURIComponent(insightId)}?${profileQuery(p)}`).then(json<RenderResponse>),
};

/** Live stream for one fan profile. Reconnects with backoff; a new profile opens a new socket. */
export function useLiveStream(params: ProfileParams): LiveState {
  const [state, dispatch] = useReducer(reduce, initialLive);
  const query = profileQuery(params);
  const retry = useRef(0);
  const stateRef = useRef(state);
  stateRef.current = state;
  const loading = useRef(false);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: number | undefined;
    let closed = false;

    const open = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws?${query}`);
      ws.onopen = () => {
        retry.current = 0;
        dispatch({ type: "connected", value: true });
      };
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data) as StreamMessage;
        // A viewer joining mid-match, or any seek, backfills the ribbon from the server's history.
        if (msg.type === "tick" && !loading.current && needsHistory(stateRef.current, msg)) {
          loading.current = true;
          Promise.all([api.momentum(), api.insights()])
            .then(([momentum, insights]) => dispatch({ type: "history", momentum, insights }))
            .catch(console.error)
            .finally(() => (loading.current = false));
        }
        dispatch(msg);
      };
      ws.onclose = () => {
        dispatch({ type: "connected", value: false });
        if (!closed) timer = window.setTimeout(open, Math.min(5000, 500 * 2 ** retry.current++));
      };
    };
    open();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      ws?.close();
    };
  }, [query]);

  return state;
}

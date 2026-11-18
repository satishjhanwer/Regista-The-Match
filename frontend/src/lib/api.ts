/**
 * REST helpers and the WebSocket hook for the Regista replay API (see docs/API.md).
 * In a static build (`VITE_STATIC=1`) both are served by the in-browser hub in `./static` instead.
 */

import { useEffect, useReducer, useRef } from "react";

import type { ControlRequest, FanProfile, Insight, MomentumPoint, RenderResponse, ReplayStatus } from "../contracts/stream";
import { initialLive, needsHistory, reduce, type LiveState, type StreamMessage } from "./live";
import { STATIC, resolveProfile, staticHub, type StaticViewer } from "./static";

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

const httpApi = {
  control: (body: ControlRequest) =>
    fetch("/api/replay", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }).then(json<ReplayStatus>),
  profiles: () => fetch("/api/profiles").then(json<FanProfile[]>),
  insights: () => fetch("/api/insights").then(json<Insight[]>),
  momentum: () => fetch("/api/momentum").then(json<MomentumPoint[]>),
  render: (insightId: string, p: ProfileParams) => fetch(`/api/render/${encodeURIComponent(insightId)}?${profileQuery(p)}`).then(json<RenderResponse>),
};

const staticApi: typeof httpApi = {
  control: (body) => staticHub().then((h) => h.control(body)),
  profiles: () => staticHub().then((h) => h.b.presets),
  insights: () => staticHub().then((h) => h.insights()),
  momentum: () => staticHub().then((h) => h.momentum()),
  render: (insightId, p) => staticHub().then((h) => h.render(insightId, p)),
};

/** Typed calls to the replay API (or, in a static build, to the in-browser hub). */
export const api = STATIC ? staticApi : httpApi;

/** Live stream for one fan profile. Reconnects with backoff; a new profile opens a new socket. */
function useSocketStream(params: ProfileParams): LiveState {
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

/** The same stream from the in-browser hub; a new profile reconnects with the closest precomputed one. */
function useStaticStream(params: ProfileParams): LiveState {
  const [state, dispatch] = useReducer(reduce, initialLive);
  const query = profileQuery(params);

  useEffect(() => {
    let viewer: StaticViewer | null = null;
    let closed = false;
    // The hub sends synchronously (a seek's reset and tick arrive before React re-renders), so history needs are
    // judged on a mirror run through the same reducer rather than on the last rendered state.
    let mirror = initialLive;
    const apply = (action: Parameters<typeof reduce>[1]) => {
      mirror = reduce(mirror, action);
      dispatch(action);
    };
    staticHub()
      .then((hub) => {
        if (closed) return;
        viewer = {
          profile: resolveProfile(hub.b, params).profile,
          send: (msg) => {
            if (msg.type === "tick" && needsHistory(mirror, msg)) apply({ type: "history", momentum: hub.momentum(), insights: hub.insights() });
            apply(msg);
          },
        };
        apply({ type: "connected", value: true });
        hub.connect(viewer);
      })
      .catch(console.error);
    return () => {
      closed = true;
      if (viewer) staticHub().then((hub) => hub.disconnect(viewer!));
    };
  }, [query]);

  return state;
}

/** Live stream for one fan profile: over the WebSocket, or from the in-browser hub in a static build. */
export const useLiveStream = STATIC ? useStaticStream : useSocketStream;

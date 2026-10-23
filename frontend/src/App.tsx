import { useEffect, useMemo, useRef, useState } from "react";

import { CompareView } from "./components/Compare";
import { FanPanel, Transport } from "./components/Controls";
import { ChaosMeter, MomentumRibbon } from "./components/Metrics";
import { OverlayLayer, ScoreBug } from "./components/Overlays";
import { Pitch } from "./components/Pitch";
import { Feed, TracePanel } from "./components/Trace";
import type { FanProfile, OverlayMessage } from "./contracts/stream";
import { api, useLiveStream, type ProfileParams } from "./lib/api";
import { palette, playerNames } from "./lib/format";
import { matchMinute } from "./lib/live";
import { emptyQueue, enqueue, tick, type QueueState } from "./lib/overlayQueue";

const DEFAULT_PARAMS: ProfileParams = { profile: "analyst-en", mode: "analyst", lang: "en", team: "", player: "", metric: "" };
const AIR_TICK_MS = 100;

export default function App() {
  const [params, setParams] = useState<ProfileParams>(DEFAULT_PARAMS);
  const [presets, setPresets] = useState<FanProfile[]>([]);
  const [tab, setTab] = useState<"live" | "compare">("live");
  const [selected, setSelected] = useState<OverlayMessage | null>(null);
  const live = useLiveStream(params);

  useEffect(() => {
    api.profiles().then(setPresets).catch(console.error);
  }, []);

  // Overlay air clock: advances only while the replay plays, so pausing holds graphics on screen.
  const [queue, setQueue] = useState<QueueState>(emptyQueue);
  const air = useRef(0);
  const fed = useRef(0);
  const liveRef = useRef(live);
  liveRef.current = live;

  useEffect(() => {
    setQueue(emptyQueue());
    fed.current = 0;
    setSelected(null);
  }, [live.resets, live.profile?.profile_id]);

  useEffect(() => {
    let last = performance.now();
    const id = window.setInterval(() => {
      const now = performance.now();
      const s = liveRef.current;
      if (s.playing) air.current += now - last;
      last = now;
      const fresh = s.overlays.slice(fed.current);
      fed.current = s.overlays.length;
      const airNow = air.current;
      const clock = s.clock?.match_clock_s ?? 0;
      setQueue((q) => tick(fresh.reduce((acc, m) => enqueue(acc, m, airNow), q), airNow, clock));
    }, AIR_TICK_MS);
    return () => window.clearInterval(id);
  }, []);

  const colors = useMemo(() => palette(live.meta), [live.meta]);
  const names = useMemo(() => playerNames(live.meta), [live.meta]);
  const minute = live.clock ? matchMinute(live.clock.period, live.clock.t) : 0;
  const traced = selected ?? live.overlays[live.overlays.length - 1] ?? null;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          REGISTA <span>the match, explained and verified</span>
        </div>
        <nav className="tabs">
          <button className={tab === "live" ? "on" : ""} onClick={() => setTab("live")}>
            Live
          </button>
          <button className={tab === "compare" ? "on" : ""} onClick={() => setTab("compare")}>
            Compare viewers
          </button>
        </nav>
        <Transport playing={live.playing} speed={live.speed} minute={minute} />
        <span className={`conn ${live.connected ? "up" : "down"}`}>{live.connected ? "live" : "reconnecting"}</span>
      </header>

      {!live.meta ? (
        <div className="boot">Connecting to the Regista replay service…</div>
      ) : tab === "compare" ? (
        <CompareView meta={live.meta} />
      ) : (
        <main className="live">
          <section className="stage">
            <div className="frame">
              <Pitch events={live.events} colors={colors} names={names} />
              <ScoreBug meta={live.meta} score={live.score} clock={live.clock} colors={colors} />
              <OverlayLayer onAir={queue.onAir} air={air.current} colors={colors} events={live.events} onSelect={setSelected} />
              <div className="venue">
                {live.meta.venue} · {live.meta.competition} · synthetic match
              </div>
            </div>
            <div className="metrics-row">
              <MomentumRibbon series={live.momentum} markers={live.markers} minute={minute} meta={live.meta} colors={colors} />
              <ChaosMeter metrics={live.metrics} meta={live.meta} colors={colors} />
            </div>
          </section>
          <aside className="side">
            <FanPanel meta={live.meta} presets={presets} params={params} onChange={setParams} />
            <Feed items={live.overlays} selected={traced?.payload.insight.insight_id ?? null} onSelect={setSelected} />
            {traced && <TracePanel insight={traced.payload.insight} rendered={traced.payload.rendered} trace={traced.trace} source={traced.source} />}
          </aside>
        </main>
      )}
    </div>
  );
}

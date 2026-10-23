// Match-long momentum ribbon and the control vs chaos meter.

import type { LiveMetrics, MatchMeta } from "../contracts/stream";
import type { Palette } from "../lib/format";
import type { Marker } from "../lib/live";

const MINUTES = 92;
const W = 1000;
const H = 90;
const MID = H / 2;

export function MomentumRibbon({
  series,
  markers,
  minute,
  meta,
  colors,
}: {
  series: { minute: number; index: number; gap: boolean }[];
  markers: Marker[];
  minute: number;
  meta: MatchMeta;
  colors: Palette;
}) {
  const x = (m: number) => (Math.min(m, MINUTES) / MINUTES) * W;
  const y = (v: number) => MID - v * (MID - 6);
  // One closed area per contiguous run of samples; seeks leave honest gaps instead of fake ramps.
  const runs: { minute: number; index: number }[][] = [];
  for (const p of series) {
    if (p.gap || runs.length === 0) runs.push([]);
    runs[runs.length - 1].push(p);
  }
  const area = runs
    .filter((r) => r.length > 1)
    .map((r) => `M${x(r[0].minute)},${MID} L${r.map((p) => `${x(p.minute).toFixed(1)},${y(p.index).toFixed(1)}`).join(" L")} L${x(r[r.length - 1].minute)},${MID} Z`)
    .join(" ");
  const home = meta.home.team_id;
  return (
    <div className="ribbon">
      <div className="panel-title">
        Momentum <span className="legend" style={{ color: colors.ink[home] }}>▲ {meta.home.short_name}</span>
        <span className="legend" style={{ color: colors.ink[meta.away.team_id] }}>▼ {meta.away.short_name}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="Momentum over the match">
        <defs>
          <clipPath id="above">
            <rect x={0} y={0} width={W} height={MID} />
          </clipPath>
          <clipPath id="below">
            <rect x={0} y={MID} width={W} height={MID} />
          </clipPath>
        </defs>
        {[15, 30, 45, 60, 75, 90].map((m) => (
          <g key={m}>
            <line x1={x(m)} y1={0} x2={x(m)} y2={H} className={m === 45 ? "grid half" : "grid"} />
            <text x={x(m) - 4} y={H - 3} className="tick-label" textAnchor="end">
              {m}′
            </text>
          </g>
        ))}
        <line x1={0} y1={MID} x2={W} y2={MID} className="axis" />
        {area && <path d={area} fill={colors.ink[home]} clipPath="url(#above)" opacity={0.85} />}
        {area && <path d={area} fill={colors.ink[meta.away.team_id]} clipPath="url(#below)" opacity={0.85} />}
        {markers.map((mk, i) => (
          <g key={i} transform={`translate(${x(mk.minute)}, ${mk.kind === "goal" ? 10 : H - 14})`}>
            <title>{`${Math.floor(mk.minute)}′ ${mk.label}`}</title>
            {mk.kind === "goal" && <circle r={6} fill="#fff" stroke={colors.ink[mk.team ?? ""] ?? "#999"} strokeWidth={3} />}
            {mk.kind === "press" && <path d="M-6,5 L0,-6 L6,5 Z" fill={colors.ink[mk.team ?? ""] ?? "#999"} />}
            {mk.kind === "chaos" && <rect x={-5} y={-5} width={10} height={10} transform="rotate(45)" fill="var(--chaos)" />}
          </g>
        ))}
        <line x1={x(minute)} y1={0} x2={x(minute)} y2={H} className="now" />
      </svg>
    </div>
  );
}

function Bar({ value, color, label }: { value: number; color: string; label: string }) {
  return (
    <div className="mini-bar">
      <span className="mb-label">{label}</span>
      <span className="mb-track">
        <span className="mb-fill" style={{ width: `${Math.round(value * 100)}%`, background: color }} />
      </span>
      <span className="mb-value">{Math.round(value * 100)}</span>
    </div>
  );
}

export function ChaosMeter({ metrics, meta, colors }: { metrics: LiveMetrics | null; meta: MatchMeta; colors: Palette }) {
  const chaos = metrics?.chaos ?? null;
  const teams = [meta.home, meta.away];
  return (
    <div className="chaos-meter">
      <div className="panel-title">Control vs chaos</div>
      <div className="gauge">
        <span className="g-end">Control</span>
        <span className="g-track">
          {chaos !== null && <span className="g-needle" style={{ left: `${chaos * 100}%` }} />}
        </span>
        <span className="g-end">Chaos</span>
      </div>
      <div className="g-value">{chaos === null ? "warming up" : `index ${chaos.toFixed(2)}`}</div>
      {teams.map((t) => (
        <Bar key={t.team_id} label={`${t.short_name} control`} value={metrics?.control[t.team_id] ?? 0} color={colors.ink[t.team_id]} />
      ))}
      {teams.map((t) => (
        <Bar key={`p-${t.team_id}`} label={`${t.short_name} press`} value={metrics?.pressed_share[t.team_id] ?? 0} color={colors.ink[t.team_id]} />
      ))}
      <div className="xg-line">
        xG {teams.map((t) => `${t.short_name} ${(metrics?.xg[t.team_id] ?? 0).toFixed(2)}`).join(" · ")}
      </div>
    </div>
  );
}

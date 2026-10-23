// Live pitch: markings plus a fading trail of the latest on-ball actions, in absolute pitch metres.

import type { StreamEvent } from "../contracts/stream";
import type { Palette } from "../lib/format";

const L = 105;
const W = 68;
const TRAIL = 22;
const DRAWN = new Set(["pass", "carry", "shot", "pressure", "tackle", "interception", "clearance", "sprint"]);

function Markings() {
  const box = (x: number, w: number, h: number) => <rect x={x} y={(W - h) / 2} width={w} height={h} />;
  return (
    <g className="pitch-lines">
      <rect x={0} y={0} width={L} height={W} />
      <line x1={L / 2} y1={0} x2={L / 2} y2={W} />
      <circle cx={L / 2} cy={W / 2} r={9.15} />
      <circle cx={L / 2} cy={W / 2} r={0.4} className="spot" />
      {box(0, 16.5, 40.3)}
      {box(L - 16.5, 16.5, 40.3)}
      {box(0, 5.5, 18.3)}
      {box(L - 5.5, 5.5, 18.3)}
      <circle cx={11} cy={W / 2} r={0.4} className="spot" />
      <circle cx={L - 11} cy={W / 2} r={0.4} className="spot" />
      <path d={`M16.5 ${W / 2 - 7.3} A9.15 9.15 0 0 1 16.5 ${W / 2 + 7.3}`} />
      <path d={`M${L - 16.5} ${W / 2 - 7.3} A9.15 9.15 0 0 0 ${L - 16.5} ${W / 2 + 7.3}`} />
      <rect x={-1.6} y={W / 2 - 3.66} width={1.6} height={7.32} className="goal" />
      <rect x={L} y={W / 2 - 3.66} width={1.6} height={7.32} className="goal" />
    </g>
  );
}

function EventMark({ e, color, opacity, latest }: { e: StreamEvent; color: string; opacity: number; latest: boolean }) {
  const ex = e.end_x ?? e.x;
  const ey = e.end_y ?? e.y;
  switch (e.type) {
    case "pass":
      return (
        <g opacity={opacity}>
          <line x1={e.x} y1={e.y} x2={ex} y2={ey} stroke={color} strokeWidth={e.is_through_ball ? 0.7 : 0.45} strokeDasharray={e.outcome === "complete" ? undefined : "1.2 1"} />
          <circle cx={ex} cy={ey} r={0.55} fill={e.outcome === "complete" ? color : "none"} stroke={color} strokeWidth={0.25} />
        </g>
      );
    case "carry":
      return <line x1={e.x} y1={e.y} x2={ex} y2={ey} stroke={color} strokeWidth={0.35} strokeDasharray="0.3 0.7" opacity={opacity} />;
    case "shot": {
      const gx = e.x > L / 2 ? L : 0;
      const goal = e.outcome === "goal";
      return (
        <g opacity={opacity}>
          <line x1={e.x} y1={e.y} x2={gx} y2={W / 2} stroke={color} strokeWidth={goal ? 0.9 : 0.5} />
          <circle cx={e.x} cy={e.y} r={goal ? 1.6 : 1.1} fill={color} stroke="#fff" strokeWidth={0.3} />
          {goal && latest && <circle cx={gx} cy={W / 2} r={3} className="goal-pulse" stroke={color} />}
        </g>
      );
    }
    case "pressure":
      return <circle cx={e.x} cy={e.y} r={1.3} fill="none" stroke={color} strokeWidth={0.3} opacity={opacity * 0.9} />;
    case "tackle":
    case "interception":
      return (
        <g opacity={opacity} stroke={color} strokeWidth={0.45}>
          <line x1={e.x - 0.9} y1={e.y - 0.9} x2={e.x + 0.9} y2={e.y + 0.9} />
          <line x1={e.x - 0.9} y1={e.y + 0.9} x2={e.x + 0.9} y2={e.y - 0.9} />
        </g>
      );
    case "clearance":
      return <line x1={e.x} y1={e.y} x2={ex} y2={ey} stroke={color} strokeWidth={0.4} strokeDasharray="2 1" opacity={opacity * 0.7} />;
    case "sprint":
      return <circle cx={e.x} cy={e.y} r={2} fill="none" stroke={color} strokeWidth={0.5} className="sprint-ring" opacity={opacity} />;
    default:
      return null;
  }
}

export function ballAt(events: StreamEvent[]): { x: number; y: number; team: string | null; player: string | null } | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (!DRAWN.has(e.type) || e.type === "pressure" || e.type === "sprint") continue;
    if (e.type === "shot") return { x: e.x > L / 2 ? L - 1 : 1, y: W / 2, team: e.team, player: e.player };
    return { x: e.end_x ?? e.x, y: e.end_y ?? e.y, team: e.team, player: e.player };
  }
  return null;
}

export function Pitch({ events, colors, names }: { events: StreamEvent[]; colors: Palette; names: Record<string, string> }) {
  const trail = events.filter((e) => DRAWN.has(e.type)).slice(-TRAIL);
  const ball = ballAt(events);
  return (
    <svg className="pitch" viewBox={`-3 -3 ${L + 6} ${W + 6}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label="Live pitch">
      <defs>
        <pattern id="stripes" width="10.5" height={W} patternUnits="userSpaceOnUse">
          <rect width="5.25" height={W} className="stripe-a" />
          <rect x="5.25" width="5.25" height={W} className="stripe-b" />
        </pattern>
      </defs>
      <rect x={-3} y={-3} width={L + 6} height={W + 6} className="pitch-surround" />
      <rect x={0} y={0} width={L} height={W} fill="url(#stripes)" />
      <Markings />
      {trail.map((e, i) => (
        <EventMark key={e.id} e={e} color={colors.ink[e.team ?? ""] ?? "#ddd"} opacity={0.2 + (0.8 * (i + 1)) / trail.length} latest={i === trail.length - 1} />
      ))}
      {ball && (
        <g className="ball" style={{ transform: `translate(${ball.x}px, ${ball.y}px)` }}>
          <circle r={1.15} fill="#fff" stroke="#111" strokeWidth={0.25} />
          {ball.player && (
            <text y={-2.2} textAnchor="middle" className="ball-label" fill={colors.ink[ball.team ?? ""] ?? "#fff"}>
              {names[ball.player] ?? ball.player}
            </text>
          )}
        </g>
      )}
    </svg>
  );
}

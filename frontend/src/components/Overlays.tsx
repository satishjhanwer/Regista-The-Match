/**
 * Broadcast graphics: score bug plus one component per overlay slot.
 */

import type { CSSProperties } from "react";

import type { MatchMeta, OverlayMessage, StreamClock, StreamEvent } from "../contracts/stream";
import { KIND_LABEL, type Palette } from "../lib/format";
import { progress, type OnAir, type Slot } from "../lib/overlayQueue";

/** Team kits, score and broadcast clock. */
export function ScoreBug({ meta, score, clock, colors }: { meta: MatchMeta; score: Record<string, number>; clock: StreamClock | null; colors: Palette }) {
  const h = meta.home;
  const a = meta.away;
  return (
    <div className="scorebug">
      <span className="kit" style={{ background: colors.kit[h.team_id], borderColor: h.secondary_color }} />
      <span className="team">{h.short_name}</span>
      <span className="score">
        {score[h.team_id] ?? 0}
        <i>–</i>
        {score[a.team_id] ?? 0}
      </span>
      <span className="team">{a.short_name}</span>
      <span className="kit" style={{ background: colors.kit[a.team_id], borderColor: a.secondary_color }} />
      <span className="clock">{clock?.display ?? "0:00"}</span>
    </div>
  );
}

function Verified({ msg }: { msg: OverlayMessage }) {
  const v = msg.payload.rendered.verification;
  return (
    <span className={`verified ${v.status}`} title={`${v.checked_claims} claims checked against facts`}>
      {v.status === "revised" ? "✓ verified after revision" : "✓ verified"}
    </span>
  );
}

function Bar({ item, air }: { item: OnAir; air: number }) {
  return <span className="ttl" style={{ transform: `scaleX(${1 - progress(item, air)})` }} />;
}

/** Team accent as a CSS custom property (React's CSSProperties has no index for custom props). */
function teamVar(color: string): CSSProperties {
  return { "--team": color } as unknown as CSSProperties;
}

function langClass(msg: OverlayMessage) {
  return `lang-${msg.payload.rendered.language}`;
}

interface SlotProps {
  item: OnAir;
  air: number;
  colors: Palette;
  onSelect: (m: OverlayMessage) => void;
}

function accent(item: OnAir, colors: Palette): string {
  const t = item.msg.payload.insight.entities.team_ids;
  return t.length === 1 ? (colors.ink[t[0]] ?? "var(--accent)") : "var(--accent)";
}

/** Main story graphic: kind, headline, body and stat callout. */
export function LowerThird({ item, air, colors, onSelect }: SlotProps) {
  const { rendered, insight } = item.msg.payload;
  return (
    <button className={`gfx lower-third ${langClass(item.msg)} kind-${insight.kind}`} style={teamVar(accent(item, colors))} onClick={() => onSelect(item.msg)}>
      <div className="lt-main">
        <div className="lt-kicker">
          <span className="chip">{KIND_LABEL[insight.kind]}</span>
          <span className="lt-clock">{insight.clock.display}</span>
          <Verified msg={item.msg} />
        </div>
        <div className="lt-headline">{rendered.headline}</div>
        <div className="lt-body">{rendered.body}</div>
      </div>
      {rendered.stat_callout && (
        <div className="lt-stat">
          <span className="value">{rendered.stat_callout.value}</span>
          <span className="label">{rendered.stat_callout.label}</span>
        </div>
      )}
      <Bar item={item} air={air} />
    </button>
  );
}

/** Analysis card listing every claim; fan-colour claims are shown in italics. */
export function SidePanel({ item, air, colors, onSelect }: SlotProps) {
  const { rendered, insight } = item.msg.payload;
  return (
    <button className={`gfx side-panel ${langClass(item.msg)}`} style={teamVar(accent(item, colors))} onClick={() => onSelect(item.msg)}>
      <div className="lt-kicker">
        <span className="chip">{KIND_LABEL[insight.kind]}</span>
        <span className="lt-clock">{insight.clock.display}</span>
      </div>
      <div className="sp-headline">{rendered.headline}</div>
      {rendered.stat_callout && (
        <div className="sp-stat">
          <span className="value">{rendered.stat_callout.value}</span>
          <span className="label">{rendered.stat_callout.label}</span>
        </div>
      )}
      <ul className="sp-claims">
        {rendered.claims.map((c, i) => (
          <li key={i} className={c.fact_ids.length ? "" : "colour"}>
            {c.text}
          </li>
        ))}
      </ul>
      <Verified msg={item.msg} />
      <Bar item={item} air={air} />
    </button>
  );
}

/** Summary strip across the top of the frame. */
export function TopBar({ item, air, onSelect }: SlotProps) {
  const { rendered } = item.msg.payload;
  return (
    <button className={`gfx top-bar ${langClass(item.msg)}`} onClick={() => onSelect(item.msg)}>
      <span className="tb-headline">{rendered.headline}</span>
      <span className="tb-body">{rendered.body}</span>
      <Bar item={item} air={air} />
    </button>
  );
}

/** One-line crawl along the bottom of the frame. */
export function Ticker({ item, onSelect }: SlotProps) {
  const { rendered, insight } = item.msg.payload;
  return (
    <button className={`gfx ticker ${langClass(item.msg)}`} onClick={() => onSelect(item.msg)}>
      <span className="chip">{KIND_LABEL[insight.kind]}</span>
      <span className="tk-text">
        <b>{rendered.headline}</b> {rendered.body}
      </span>
    </button>
  );
}

/** Player tag: pinned where the tagged event happened, if it is still on the trail. */
export function PlayerTag({ item, air, colors, onSelect, events }: SlotProps & { events: StreamEvent[] }) {
  const { rendered, insight } = item.msg.payload;
  const ref = insight.facts[0]?.evidence.find((e) => e.kind === "event")?.ref;
  const ev = events.find((e) => e.id === ref);
  const pos = ev ? { left: `${((ev.x + 3) / 111) * 100}%`, top: `${((ev.y + 3) / 74) * 100}%` } : { right: "3%", top: "18%" };
  return (
    <button className={`gfx player-tag ${langClass(item.msg)}`} style={{ ...pos, ...teamVar(accent(item, colors)) }} onClick={() => onSelect(item.msg)}>
      <span className="pt-name">{rendered.headline}</span>
      {rendered.stat_callout && !rendered.headline.includes(rendered.stat_callout.value) && <span className="pt-stat">{rendered.stat_callout.value}</span>}
      <Bar item={item} air={air} />
    </button>
  );
}

/** Draws whatever the scheduler has on air, one component per slot. */
export function OverlayLayer({
  onAir,
  air,
  colors,
  events,
  onSelect,
}: {
  onAir: Partial<Record<Slot, OnAir>>;
  air: number;
  colors: Palette;
  events: StreamEvent[];
  onSelect: (m: OverlayMessage) => void;
}) {
  const p = { air, colors, onSelect };
  return (
    <div className="overlay-layer">
      {onAir.top_bar && <TopBar key={onAir.top_bar.key} item={onAir.top_bar} {...p} />}
      {onAir.side_panel && <SidePanel key={onAir.side_panel.key} item={onAir.side_panel} {...p} />}
      {onAir.player_tag && <PlayerTag key={onAir.player_tag.key} item={onAir.player_tag} events={events} {...p} />}
      {onAir.lower_third && <LowerThird key={onAir.lower_third.key} item={onAir.lower_third} {...p} />}
      {onAir.ticker && <Ticker key={onAir.ticker.key} item={onAir.ticker} {...p} />}
    </div>
  );
}

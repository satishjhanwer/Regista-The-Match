"""Precompute the whole replay for the static demo (GitHub Pages, no backend).

Runs the match once through the real pipeline and the real hub code, then writes one JSON bundle the frontend's
static mode replays in the browser:

- every event (compact, as the pitch draws it) with its clock, and the hub's tick metrics and score after it
- momentum samples, and every insight with the replay time it fired
- every rendering for a fixed set of viewer profiles: the five presets, analyst and casual x 3 languages x 3 club
  choices, and Player focus x 3 languages x 5 key players. Renderings come from the recorded Foundry Local run
  where it has them (real model drafts and Verifier rejections in the trace), templates otherwise, as in demo mode.

    python scripts/export_static.py                       # -> ../frontend/public/demo/bundle.json
    python scripts/export_static.py --cache none --out x.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from regista.agents.orchestrator import WarmPath  # noqa: E402
from regista.agents.profiles import PRESETS, display_for, profile_from_params  # noqa: E402
from regista.api.app import DEFAULT_MATCH, load_match  # noqa: E402
from regista.api.hub import Hub, compact_event, trace_steps  # noqa: E402
from regista.api.replay import Replay  # noqa: E402
from regista.contracts.insight import FanProfile  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = ROOT / "data" / "RGS-2026-0001.renders.foundry-local.json"
DEFAULT_OUT = ROOT / "frontend" / "public" / "demo" / "bundle.json"
FOCUS_PLAYERS = ("NVL-09", "NVL-07", "SLM-09", "SLM-06", "SLM-11")
LANGS = ("en", "es", "hi")


def profile_set() -> list[FanProfile]:
    """The viewer profiles the static demo can show; any other choice falls back to the closest of these."""

    def fields(p: FanProfile) -> tuple:
        return p.mode, p.language, p.favorite_team_id, p.focus_player_id, p.metric_of_interest

    out: dict[tuple, FanProfile] = {fields(p): p for p in PRESETS.values()}  # a preset keeps its own id
    for lang in LANGS:
        for mode in ("analyst", "casual"):
            for team in ("", "NVL", "SLM"):
                p = profile_from_params(None, mode, lang, team, "", "")
                out.setdefault(fields(p), p)
        for player in FOCUS_PLAYERS:
            p = profile_from_params(None, "player_focus", lang, "", player, "")
            out.setdefault(fields(p), p)
    return list(out.values())


def _dump(model) -> dict:
    return model.model_dump(mode="json")


async def build(match_path: Path, cache_path: Path | None) -> dict:
    """The bundle as a JSON-ready dict."""
    match = load_match(match_path)
    cache = WarmPath.load_cache(cache_path) if cache_path and cache_path.exists() else None
    warm = WarmPath(match.meta, None, cache=cache)
    replay = Replay(match)
    hub = Hub(replay, warm, autoplay=False)

    events, elapsed, match_clock, ticks, momentum, fired = [], [], [], [], [], []
    while not replay.finished:
        n_mom = len(replay.momentum)
        step = replay.advance_to(replay.events[replay.cursor].elapsed_s)
        tick = hub.tick_message()
        for ev in step.events:
            events.append(_dump(compact_event(ev)))
            elapsed.append(ev.elapsed_s)
            match_clock.append(ev.match_clock_s)
            ticks.append({"score": tick.score, "metrics": _dump(tick.metrics)})
        momentum += [[replay.clock_s, m, i] for m, i in replay.momentum[n_mom:]]
        fired += [[ctx.elapsed_s, ctx.insight.insight_id] for ctx in step.moments]

    insights = {c.insight.insight_id: _dump(c.insight) for c in replay.history}
    renders: dict[str, list] = {}
    for profile in profile_set():
        rows = []
        for ctx in replay.history:
            res = await warm.render(ctx, profile)
            if res.rendered.verification.status not in ("verified", "revised"):
                continue  # nothing unverified, as on the live hub
            display = display_for(res.insight, profile)
            row = {
                "id": ctx.insight.insight_id,
                "source": res.source,
                "rendered": _dump(res.rendered),
                "display": _dump(display) if display else None,
                "trace": [_dump(s) for s in trace_steps(res.trace)],
            }
            if res.insight.facts != ctx.insight.facts:  # the Analyst promoted tool facts into this rendering
                row["insight"] = _dump(res.insight)
            rows.append(row)
        renders[profile.profile_id] = rows

    return {
        "version": 1,
        "match": _dump(match.meta),
        "presets": [_dump(p) for p in PRESETS.values()],
        "profiles": [_dump(p) for p in profile_set()],
        "end_s": replay.end_s,
        "events": events,
        "elapsed": elapsed,
        "match_clock": match_clock,
        "ticks": ticks,
        "momentum": momentum,
        "insights": insights,
        "fired": fired,
        "renders": renders,
        "recorded_from": cache_path.name if cache else None,
    }


def main() -> None:
    """Build the bundle and write it."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", type=Path, default=DEFAULT_MATCH)
    ap.add_argument("--cache", default=str(DEFAULT_CACHE), help="recorded agent run to use, or 'none' for templates only")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    cache = None if args.cache == "none" else Path(args.cache)
    bundle = asyncio.run(build(args.match, cache))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    n = sum(len(r) for r in bundle["renders"].values())
    size = args.out.stat().st_size / 1e6
    print(f"wrote {args.out}: {size:.1f} MB, {len(bundle['events'])} events, {n} renderings, {len(bundle['profiles'])} profiles")


if __name__ == "__main__":
    main()

"""Record a warm-path run for deterministic demos, or inspect one.

    python -m regista.agents record ../data/RGS-2026-0001.json --out ../data/RGS-2026-0001.renders.json
    python -m regista.agents show ../data/RGS-2026-0001.renders.json [--profile analyst-en]

``record`` replays the match, captures each insight's context (recaps included),
and renders it for every preset profile it is relevant to, with the LLM provider
configured in backend/.env (or the template Narrator when none is). Serve the result
with REGISTA_AGENT_CACHE=<file>, so a recorded take never waits on a model or a rate limit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter
from pathlib import Path

from ..contracts.events import MatchFile
from ..llm import build_chat_client, resolve_provider
from .orchestrator import WarmPath
from .profiles import PRESETS, display_for


async def record(match: MatchFile, out: Path, profiles: list[str], concurrency: int, kinds: set[str] | None = None) -> None:
    from ..api.replay import Replay

    provider = resolve_provider()
    warm = WarmPath(match.meta, build_chat_client(provider))
    replay = Replay(match)
    replay.advance_to(replay.end_s)
    moments = [c for c in replay.history if kinds is None or c.insight.kind in kinds]
    jobs = [(ctx, PRESETS[p]) for ctx in moments for p in profiles if display_for(ctx.insight, PRESETS[p]) is not None]
    print(f"rendering {len(jobs)} (insight, profile) pairs from {len(moments)} insights", flush=True)
    sem = asyncio.Semaphore(concurrency)
    t0 = time.perf_counter()

    async def one(ctx, profile):
        async with sem:
            return await warm.render(ctx, profile)

    results = await asyncio.gather(*(one(c, p) for c, p in jobs))
    warm.save_cache(out)
    sources = Counter(r.source for r in results)
    rejected = sum(s.status == "rejected" for r in results for s in r.trace if s.agent == "verifier")
    print(f"provider={provider} insights={len(replay.history)} renders={len(results)} in {time.perf_counter() - t0:.1f}s")
    print(f"sources: {dict(sources)}; verifier rejections along the way: {rejected}")
    print(f"wrote {out}")


def show(path: Path, profile: str | None) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    for row in data["renders"]:
        if profile and row["profile_id"] != profile:
            continue
        r, ins = row["rendered"], row["insight"]
        print(f"{ins['clock']['display']:>9} {ins['kind']:<16} {row['profile_id']:<15} [{row['source']}] {r['headline']} | {r['body']}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="regista.agents")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("match", type=Path)
    rec.add_argument("--out", type=Path, required=True)
    rec.add_argument("--profiles", default=",".join(PRESETS))
    rec.add_argument("--concurrency", type=int, default=4, help="parallel renders; use 1 for a CPU-only local model")
    rec.add_argument("--kinds", help="only these insight kinds, e.g. goal,press_change,milestone,recap")
    sh = sub.add_parser("show")
    sh.add_argument("path", type=Path)
    sh.add_argument("--profile")
    args = ap.parse_args()
    if args.cmd == "record":
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        match = MatchFile.model_validate(json.loads(args.match.read_text(encoding="utf-8")))
        kinds = set(args.kinds.split(",")) if args.kinds else None
        asyncio.run(record(match, args.out, args.profiles.split(","), args.concurrency, kinds))
    else:
        show(args.path, args.profile)


if __name__ == "__main__":
    main()

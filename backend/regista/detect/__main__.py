"""Replay a match through state + detectors and print the insight timeline.

python -m regista.detect ../data/RGS-2026-0001.json [--json out.jsonl]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from ..contracts.events import MatchFile
from .pipeline import run_match


def headline(ins, n: int = 4) -> str:
    """The first ``n`` facts of an insight, as one readable line."""
    parts = []
    for f in ins.facts[:n]:
        unit = "" if f.unit is None else ("%" if f.unit == "%" else f" {f.unit}")
        prev = "" if f.previous_value is None else f" (was {f.previous_value})"
        parts.append(f"{f.label}: {f.value}{unit}{prev}")
    return "; ".join(parts)


def main() -> None:
    """Command-line entry point."""
    ap = argparse.ArgumentParser(prog="regista.detect")
    ap.add_argument("path", type=Path)
    ap.add_argument("--json", type=Path, help="also write insights as JSON lines")
    args = ap.parse_args()

    match = MatchFile.model_validate(json.loads(args.path.read_text(encoding="utf-8")))
    t0 = time.perf_counter()
    insights, timings = run_match(match)
    wall = time.perf_counter() - t0

    for ins in insights:
        print(f"{ins.clock.display:>9}  {ins.kind:<16} p{ins.priority}  {headline(ins)}")
    ordered = sorted(timings)
    p95 = ordered[int(0.95 * (len(ordered) - 1))]
    print(
        f"\n{len(insights)} insights from {len(timings)} events; wall {wall * 1e3:.0f} ms;"
        f" per event mean {sum(timings) / len(timings) * 1e6:.0f} us, p95 {p95 * 1e6:.0f} us, max {ordered[-1] * 1e3:.2f} ms"
    )
    if args.json:
        args.json.write_text("".join(i.model_dump_json() + "\n" for i in insights), encoding="utf-8")


if __name__ == "__main__":
    main()

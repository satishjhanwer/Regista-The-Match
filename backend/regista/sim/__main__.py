"""CLI: generate a match and print a storyline sanity summary.

python -m regista.sim generate --seed 7 --out ../data
python -m regista.sim summary ../data/RGS-2026-0001.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from ..contracts.events import MatchFile, format_clock, match_minute
from .engine import simulate


def _write(seed: int, match_id: str, out: Path) -> Path:
    match, truth = simulate(seed=seed, match_id=match_id)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{match_id}.json"
    path.write_text(match.model_dump_json(indent=None), encoding="utf-8")
    (out / f"{match_id}.truth.json").write_text(truth.model_dump_json(indent=2), encoding="utf-8")
    return path


def summarize(match: MatchFile, bin_min: int = 15) -> str:
    """Per-window storyline table (completion, pressures, shots, turnovers) for a simulated match."""
    home, away = match.meta.home.team_id, match.meta.away.team_id
    bins: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for e in match.events:
        b = int(match_minute(e.period, e.t) // bin_min)
        s = bins[b]
        if e.type == "pass":
            s[f"{e.team_id}.passes"] += 1
            s[f"{e.team_id}.complete"] += e.outcome == "complete"
            s[f"{e.team_id}.long"] += e.length_m > 32
        elif e.type == "pressure":
            s[f"{e.team_id}.pressures"] += 1
        elif e.type == "shot":
            s[f"{e.team_id}.shots"] += 1
        elif e.type == "possession_change":
            s["turnovers"] += e.cause in ("tackle", "interception")
    lines = [f"{'window':>9} | {home} pass% {home} pass#  {away} press | {away} pass% {away} pass#  {home} press | shots H-A | turnovers"]
    for b in sorted(bins):
        s = bins[b]

        def pct(team: str, s=s) -> str:
            n = s[f"{team}.passes"]
            return f"{100 * s[f'{team}.complete'] / n:5.1f}" if n else "  -  "

        lines.append(
            f"{b * bin_min:>3}-{(b + 1) * bin_min:<3}'  | {pct(home):>9} {int(s[f'{home}.passes']):>9} {int(s[f'{away}.pressures']):>9} |"
            f" {pct(away):>9} {int(s[f'{away}.passes']):>9} {int(s[f'{home}.pressures']):>9} |"
            f" {int(s[f'{home}.shots']):>3}-{int(s[f'{away}.shots']):<3}    | {int(s['turnovers']):>5}"
        )
    goals = [f"{format_clock(e.period, e.t)} {e.team_id} {e.player_id}" for e in match.events if e.type == "shot" and e.outcome == "goal"]
    lines.append(f"events={len(match.events)}  goals: " + "; ".join(goals))
    return "\n".join(lines)


def main() -> None:
    """Command-line entry point: ``generate`` or ``summary``."""
    ap = argparse.ArgumentParser(prog="regista.sim")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--match-id", default="RGS-2026-0001")
    g.add_argument("--out", type=Path, default=Path("../data"))
    s = sub.add_parser("summary")
    s.add_argument("path", type=Path)
    args = ap.parse_args()

    if args.cmd == "generate":
        path = _write(args.seed, args.match_id, args.out)
        print(f"wrote {path} and truth file")
        print(summarize(MatchFile.model_validate(json.loads(path.read_text(encoding="utf-8")))))
    else:
        print(summarize(MatchFile.model_validate(json.loads(args.path.read_text(encoding="utf-8")))))


if __name__ == "__main__":
    main()

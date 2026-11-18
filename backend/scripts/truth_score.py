"""Truth score: do the detectors find tactical changes planted at times they cannot expect, and only those?

Each seed is simulated with ``random_plan(seed)``: one or two changes (press switch, chaos spell, control spell)
of random side, strength, start and length, or none at all in one match in four (controls). The real hot path runs
on the events; the planted windows come from the truth file, read here only, after the run.

A change counts as found when an insight of its mechanism fires in the same half between the change's start and
5 minutes after its end. Before the start is not allowed: the detectors never see ahead. Reported per mechanism
and strength: recall, minutes to detect (median, 90th percentile), whether the insight names the right side, and
false alarms (insights of these kinds that match no planted change) per match, on planted and on control matches.
Matches with no plant still have organic swings; an insight there is counted as a false alarm all the same.

Seeds 101-148 by default; models and call rates were fitted on seeds 1-5 and nothing was tuned on these.

    python scripts/truth_score.py               # 48 matches, about 20 s
    python scripts/truth_score.py --seeds 101-148 --markdown
"""

from __future__ import annotations

import argparse
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from regista.contracts.events import GroundTruth, Storyline
from regista.contracts.insight import Insight
from regista.detect import run_match
from regista.sim.engine import simulate
from regista.sim.plans import random_plan

GRACE_S = 300.0
HALF_S = 2700.0
SCORED = ("press", "chaos", "control")


def mechanism_of(ins: Insight) -> tuple[str, str | None] | None:
    """The mechanism an insight reports, with its side: press and control name a team, chaos does not."""
    if ins.kind == "press_change":
        return "press", ins.entities.team_ids[0]
    if ins.kind == "control_vs_chaos":
        return ("control", ins.entities.team_ids[0]) if ins.entities.team_ids else ("chaos", None)
    return None


def _half(clock_s: float) -> int:
    return 1 if clock_s < HALF_S else 2


@dataclass
class Plant:
    """One planted change and what the detectors made of it."""

    seed: int
    storyline: Storyline
    delay_min: float | None = None  # None: missed
    right_side: bool | None = None


@dataclass
class MatchScore:
    """Every planted change of one match, and the insights that matched none."""

    seed: int
    plants: list[Plant] = field(default_factory=list)
    false_alarms: list[Insight] = field(default_factory=list)

    @property
    def control(self) -> bool:
        """True when nothing was planted."""
        return not self.plants


def score_match(seed: int, truth: GroundTruth, insights: list[Insight]) -> MatchScore:
    """Match each scored storyline to the first insight of its mechanism in its window; the rest are false alarms."""
    out = MatchScore(seed)
    plants = [s for s in truth.storylines if s.mechanism in SCORED]
    claimed: set[str] = set()
    for s in plants:
        plant = Plant(seed, s)
        hits = [
            ins
            for ins in insights
            if (m := mechanism_of(ins))
            and m[0] == s.mechanism
            and ins.clock.period == _half(s.start_clock_s)
            and s.start_clock_s <= ins.clock.match_clock_s <= s.end_clock_s + GRACE_S
        ]
        if hits:
            first = hits[0]
            plant.delay_min = (first.clock.match_clock_s - s.start_clock_s) / 60.0
            plant.right_side = s.team_id is None or mechanism_of(first)[1] == s.team_id
            claimed |= {h.insight_id for h in hits}  # a re-announcement inside the window is not a false alarm
        out.plants.append(plant)
    out.false_alarms = [ins for ins in insights if mechanism_of(ins) and ins.insight_id not in claimed]
    return out


def run(seeds: list[int]) -> list[MatchScore]:
    """Simulate, detect and score each seed with its random plan."""
    scores = []
    for seed in seeds:
        match, truth = simulate(seed=seed, match_id=f"RGS-TRUTH-{seed:04d}", plan=random_plan(seed))
        insights, _ = run_match(match)
        scores.append(score_match(seed, truth, insights))
    return scores


def summarize(scores: list[MatchScore]) -> dict:
    """Recall, delay and side accuracy per mechanism and strength; false alarms per match."""
    groups: dict[str, list[Plant]] = defaultdict(list)
    for sc in scores:
        for p in sc.plants:
            groups["all"].append(p)
            groups[p.storyline.mechanism].append(p)
            groups[f"{p.storyline.mechanism} ({p.storyline.difficulty})"].append(p)
    rows = {}
    for name, plants in groups.items():
        found = [p for p in plants if p.delay_min is not None]
        delays = sorted(p.delay_min for p in found)
        rows[name] = {
            "planted": len(plants),
            "found": len(found),
            "recall": len(found) / len(plants),
            "median_min": statistics.median(delays) if delays else None,
            "p90_min": delays[min(len(delays) - 1, int(0.9 * len(delays)))] if delays else None,
            "right_side": sum(bool(p.right_side) for p in found) / len(found) if found else None,
        }
    planted = [sc for sc in scores if not sc.control]
    controls = [sc for sc in scores if sc.control]
    alarms = defaultdict(int)
    for sc in scores:
        for ins in sc.false_alarms:
            alarms[mechanism_of(ins)[0]] += 1
    return {
        "matches": len(scores),
        "controls": len(controls),
        "rows": rows,
        "false_alarms_per_match": sum(len(sc.false_alarms) for sc in scores) / len(scores),
        "false_alarms_per_planted_match": sum(len(sc.false_alarms) for sc in planted) / max(1, len(planted)),
        "false_alarms_per_control": sum(len(sc.false_alarms) for sc in controls) / max(1, len(controls)),
        "false_alarms_by_mechanism": {m: alarms[m] / len(scores) for m in SCORED},
    }


def _fmt(v, pct: bool = False) -> str:
    if v is None:
        return "-"
    return f"{v:.0%}" if pct else f"{v:.1f}"


def render(summary: dict, markdown: bool) -> str:
    """The summary as a table (markdown or plain)."""
    head = ["change", "planted", "found", "recall", "median min to detect", "p90 min", "right side"]
    order = ["all"] + [k for m in SCORED for k in (m, f"{m} (strong)", f"{m} (moderate)")]
    body = [
        [k, str(r["planted"]), str(r["found"]), _fmt(r["recall"], True), _fmt(r["median_min"]), _fmt(r["p90_min"])]
        + [_fmt(r["right_side"], True)]
        for k in order
        if (r := summary["rows"].get(k))
    ]
    fa = summary["false_alarms_by_mechanism"]
    lines = [
        f"{summary['matches']} matches, {summary['controls']} of them controls with nothing planted.",
        "",
    ]
    if markdown:
        lines += ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(r) + " |" for r in body]
    else:
        widths = [max(len(x) for x in col) for col in zip(head, *body, strict=True)]
        lines += ["  ".join(x.ljust(w) for x, w in zip(row, widths, strict=True)) for row in [head, *body]]
    lines += [
        "",
        f"False alarms per match: {summary['false_alarms_per_match']:.2f} "
        f"(planted matches {summary['false_alarms_per_planted_match']:.2f}, controls {summary['false_alarms_per_control']:.2f}); "
        + ", ".join(f"{m} {v:.2f}" for m, v in fa.items())
        + ".",
    ]
    return "\n".join(lines)


def _seeds(spec: str) -> list[int]:
    lo, _, hi = spec.partition("-")
    return list(range(int(lo), int(hi or lo) + 1))


def main() -> None:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", default="101-148", help="inclusive range, e.g. 101-148")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()
    print(render(summarize(run(_seeds(args.seeds))), args.markdown))


if __name__ == "__main__":
    main()

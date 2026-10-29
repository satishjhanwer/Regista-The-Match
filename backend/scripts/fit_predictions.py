"""Fit the predictor's stated chances (hit rate per call kind) and report how they hold up on unseen matches.

Training uses simulated seeds 1-5; seed 7 (the demo match) and seeds 8-25 are held out. Calls are graded from
the event stream exactly as at runtime, so no ground truth is read here either.

    python scripts/fit_predictions.py            # fit, report, write regista/state/models/predictions.json
    python scripts/fit_predictions.py --dry-run  # fit and report only
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from regista.detect import InsightPipeline  # noqa: E402
from regista.detect.predict import CALL_KINDS, Predictor  # noqa: E402
from regista.sim.engine import simulate  # noqa: E402
from regista.state.logistic import MODELS_DIR  # noqa: E402

TRAIN_SEEDS = (1, 2, 3, 4, 5)
HELD_OUT_SEEDS = (7, *range(8, 26))


def outcomes(seeds) -> dict[str, list[bool]]:
    """Graded call outcomes per kind over the given seeds."""
    out: dict[str, list[bool]] = defaultdict(list)
    for seed in seeds:
        match, _ = simulate(seed=seed)
        predictor = Predictor(base_rates={})
        pipe = InsightPipeline(match.meta, predictor=predictor)
        for ev in match.events:
            pipe.process(ev)
        for call, right in predictor.graded:
            out[call.kind].append(right)
    return out


def fit(train: dict[str, list[bool]]) -> dict[str, dict]:
    """Hit rate per kind with add-one smoothing, so a small sample never states 0% or 100%."""
    rates = {}
    for kind in CALL_KINDS:
        hits = train.get(kind, [])
        rates[kind] = {"p": round((sum(hits) + 1) / (len(hits) + 2), 3), "n": len(hits), "hits": sum(hits)}
    return rates


def report(rates: dict[str, dict], held_out: dict[str, list[bool]]) -> list[str]:
    """Stated chance vs held-out hit rate, and the Brier score against a coin flip (0.25)."""
    lines = [f"{'kind':<18}{'train':>14}{'stated':>8}{'held-out':>16}{'Brier':>8}"]
    for kind in CALL_KINDS:
        r, hits = rates[kind], held_out.get(kind, [])
        rate = f"{sum(hits)}/{len(hits)} = {sum(hits) / len(hits):.0%}" if hits else "-"
        b = sum((r["p"] - h) ** 2 for h in hits) / len(hits) if hits else float("nan")
        lines.append(f"{kind:<18}{r['hits']:>6}/{r['n']:<7}{r['p']:>8.0%}{rate:>16}{b:>8.3f}")
    return lines


def main() -> None:
    """Fit on the training seeds, report on the held-out seeds, and write the rates unless --dry-run."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    rates = fit(outcomes(TRAIN_SEEDS))
    print("\n".join(report(rates, outcomes(HELD_OUT_SEEDS))))
    if not args.dry_run:
        path = MODELS_DIR / "predictions.json"
        path.write_text(json.dumps(rates, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()

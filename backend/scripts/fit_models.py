"""Fit the pass-difficulty and xG models offline and write their coefficients.

Training uses simulated seeds 1-5 only; seed 7 (the demo match) is held out
for evaluation. This script may read ground truth (true coefficients, xg_true);
the runtime state engine never does.

    python scripts/fit_models.py            # fit, report, write regista/state/models/*.json
    python scripts/fit_models.py --dry-run  # fit and report only
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from regista.sim.engine import simulate  # noqa: E402
from regista.state.logistic import (  # noqa: E402
    MODELS_DIR,
    PASS_FEATURES,
    XG_FEATURES,
    LogisticModel,
    brier,
    calibration,
    expected_brier,
    fit_logistic,
    pass_features,
    shot_features,
)

TRAIN_SEEDS = (1, 2, 3, 4, 5)
EVAL_SEED = 7
TRUTH_PASS_KEYS = ("length_per_m", "passer_defenders_5m", "receiver_defenders_5m", "high")
TRUTH_XG_KEYS = ("distance_per_m", "angle_per_rad", "header", "defenders_5m")


def pass_data(seeds):
    rows, y = [], []
    for seed in seeds:
        match, _ = simulate(seed=seed)
        for e in match.events:
            if e.type == "pass":
                rows.append(pass_features(e))
                y.append(1.0 if e.outcome == "complete" else 0.0)
    return rows, y


def print_coefs(fitted: LogisticModel, truth: dict[str, float], truth_keys: tuple[str, ...]) -> None:
    print(f"  {'term':<24}{'fitted':>10}{'truth':>10}")
    print(f"  {'intercept':<24}{fitted.intercept:>10.3f}{truth['intercept']:>10.3f}")
    for f, c, tk in zip(fitted.features, fitted.coef, truth_keys, strict=True):
        print(f"  {f:<24}{c:>10.3f}{truth[tk]:>10.3f}")


def print_calibration(p, y) -> None:
    print(f"  {'bin':<5}{'n':>6}{'mean pred':>11}{'observed':>10}")
    for i, (n, mp, mo) in enumerate(calibration(p, y, 5)):
        print(f"  {i + 1:<5}{n:>6}{mp:>11.3f}{mo:>10.3f}")


def fit_pass(write: bool) -> LogisticModel:
    rows, y = pass_data(TRAIN_SEEDS)
    b0, b = fit_logistic(rows, y)
    base_rate = sum(y) / len(y)
    model = LogisticModel(
        "pass_model",
        PASS_FEATURES,
        b0,
        tuple(b),
        {"label": "P(pass complete)", "trained_on_seeds": list(TRAIN_SEEDS), "n_train": len(y), "train_base_rate": round(base_rate, 6)},
    )
    _, truth = simulate(seed=EVAL_SEED)
    ev_rows, ev_y = pass_data([EVAL_SEED])
    p = [model.predict(r) for r in ev_rows]
    print(f"Pass model: trained on seeds {list(TRAIN_SEEDS)} ({len(y)} passes), evaluated on seed {EVAL_SEED} ({len(ev_y)} passes)")
    print_coefs(model, truth.pass_model, TRUTH_PASS_KEYS)
    base_brier = brier([base_rate] * len(ev_y), ev_y)
    print(f"  Brier seed {EVAL_SEED}: model {brier(p, ev_y):.4f}  vs constant rate {base_rate:.3f}: {base_brier:.4f}")
    print_calibration(p, ev_y)
    if write:
        (MODELS_DIR / "pass_model.json").write_text(model.to_json(), encoding="utf-8")
    return model


def shot_data(seeds):
    """Shot features with soft labels xg_true (organic shots never score, so outcomes carry no signal)."""
    rows, q = [], []
    for seed in seeds:
        match, truth = simulate(seed=seed)
        xg_true = {s.event_id: s.xg_true for s in truth.shots}
        for e in match.events:
            if e.type == "shot":
                rows.append(shot_features(e))
                q.append(xg_true[e.event_id])
    return rows, q


def fit_xg(write: bool) -> LogisticModel:
    rows, q = shot_data(TRAIN_SEEDS)
    b0, b = fit_logistic(rows, q)
    mean_xg = sum(q) / len(q)
    model = LogisticModel(
        "xg_model",
        XG_FEATURES,
        b0,
        tuple(b),
        {"label": "P(goal | shot)", "trained_on_seeds": list(TRAIN_SEEDS), "n_train": len(q), "train_mean_xg": round(mean_xg, 6)},
    )
    _, truth = simulate(seed=EVAL_SEED)
    ev_rows, ev_q = shot_data([EVAL_SEED])
    p = [model.predict(r) for r in ev_rows]
    base = [mean_xg] * len(ev_q)
    print()
    print(f"xG model: trained on seeds {list(TRAIN_SEEDS)} ({len(q)} shots, soft labels xg_true)", end="")
    print(f", evaluated on seed {EVAL_SEED} ({len(ev_q)} shots)")
    print_coefs(model, truth.xg_model, TRUTH_XG_KEYS)
    eb_model, eb_base = expected_brier(p, ev_q), expected_brier(base, ev_q)
    print(f"  expected Brier seed {EVAL_SEED}: model {eb_model:.4f}  vs mean xG {mean_xg:.3f}: {eb_base:.4f}")
    print(f"  MSE vs xg_true seed {EVAL_SEED}:  model {brier(p, ev_q):.6f}  vs mean xG: {brier(base, ev_q):.6f}")
    print(f"  total xG seed {EVAL_SEED}: model {sum(p):.2f}  truth {sum(ev_q):.2f}")
    print_calibration(p, ev_q)

    # Robustness check (not written): what 150 binary outcomes would support. Outcomes ~ Bernoulli(xg_true), seeded.
    rng = random.Random(0)
    sampled = [1.0 if rng.random() < x else 0.0 for x in q]
    s0, s = fit_logistic(rows, sampled, l2=1.0)
    alt = LogisticModel("xg_sampled", XG_FEATURES, s0, tuple(s))
    p_alt = [alt.predict(r) for r in ev_rows]
    print(f"  check: fit on sampled binary outcomes ({int(sum(sampled))} goals / {len(sampled)} shots, ridge 1.0):")
    print("    coefs " + ", ".join(f"{f}={c:.3f}" for f, c in zip(XG_FEATURES, s, strict=True)) + f", intercept={s0:.3f}")
    print(f"    expected Brier seed {EVAL_SEED}: {expected_brier(p_alt, ev_q):.4f}")
    if write:
        (MODELS_DIR / "xg_model.json").write_text(model.to_json(), encoding="utf-8")
    return model


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    fit_pass(not args.dry_run)
    fit_xg(not args.dry_run)


if __name__ == "__main__":
    main()

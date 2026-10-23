"""Offline-fitted models: held-out quality on seed 7 and runtime wiring."""

from __future__ import annotations

from regista.state import replay
from regista.state.logistic import LogisticModel, brier, fit_logistic, pass_features, sigmoid
from regista.state.models import PassDifficulty


def test_fit_recovers_known_coefficients():
    import random

    rng = random.Random(0)
    rows, y = [], []
    for _ in range(4000):
        x = (rng.uniform(0, 40), float(rng.randint(0, 3)))
        rows.append(x)
        y.append(1.0 if rng.random() < sigmoid(2.0 - 0.08 * x[0] - 0.5 * x[1]) else 0.0)
    b0, (b1, b2) = fit_logistic(rows, y)
    assert abs(b0 - 2.0) < 0.3 and abs(b1 + 0.08) < 0.015 and abs(b2 + 0.5) < 0.12


def test_pass_model_trained_on_seeds_1_to_5_only():
    model = LogisticModel.load("pass_model")
    assert model.info["trained_on_seeds"] == [1, 2, 3, 4, 5]


def test_pass_model_beats_constant_rate_on_seed_7(sims):
    match, _ = sims[7]
    model = LogisticModel.load("pass_model")
    passes = [e for e in match.events if e.type == "pass"]
    y = [1.0 if e.outcome == "complete" else 0.0 for e in passes]
    p = [model.predict(pass_features(e)) for e in passes]
    base = model.info["train_base_rate"]
    assert brier(p, y) < brier([base] * len(y), y) - 0.02


def test_pass_difficulty_component(sims):
    match, _ = sims[7]
    comp = PassDifficulty()
    st, updates = replay(match.meta, match.events, [comp])
    passes = [e for e in match.events if e.type == "pass"]
    assert len(comp.p_complete) == len(passes)
    through = next(e for e in passes if e.is_through_ball)
    assert 0.0 < comp.difficulty(through.event_id) < 1.0
    assert any(u.key == "NVL.completion_over_expected_5m" for u in updates)

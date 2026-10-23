"""Shared fixtures: simulated matches for the acceptance seeds, simulated once per session."""

from __future__ import annotations

import pytest

from regista.sim.engine import simulate

ACCEPTANCE_SEEDS = [1, 2, 3, 4, 5, 7]


@pytest.fixture(scope="session")
def sims():
    return {seed: simulate(seed=seed) for seed in ACCEPTANCE_SEEDS}

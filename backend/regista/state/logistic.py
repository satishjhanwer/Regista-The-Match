"""Small logistic-regression toolkit: features, prediction, offline fitting, scoring.

Pure Python. Fitting is Newton-Raphson on the (optionally soft-labelled) log
loss with a tiny ridge term; with four features it converges in a handful of
iterations on a few thousand rows. Only ``backend/scripts`` fits models; the
hot path only loads coefficients and predicts.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

MODELS_DIR = Path(__file__).parent / "models"

PASS_FEATURES = ("length_m", "passer_defenders_5m", "receiver_defenders_5m", "high")
XG_FEATURES = ("distance_m", "angle_rad", "header", "defenders_5m")


def pass_features(ev) -> tuple[float, ...]:
    """Pass model inputs, in ``PASS_FEATURES`` order."""
    return (ev.length_m, float(ev.pressure.defenders_within_5m), float(ev.receiver_defenders_within_5m), float(ev.height == "high"))


def shot_features(ev) -> tuple[float, ...]:
    """xG model inputs, in ``XG_FEATURES`` order."""
    return (ev.distance_m, ev.angle_rad, float(ev.body_part == "head"), float(ev.pressure.defenders_within_5m))


def sigmoid(z: float) -> float:
    """Numerically stable logistic function."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


@dataclass(frozen=True)
class LogisticModel:
    """Coefficients of one fitted logistic model, plus fitting metadata in ``info`` (seeds, sample size, base rate)."""

    name: str
    features: tuple[str, ...]
    intercept: float
    coef: tuple[float, ...]
    info: dict = field(default_factory=dict, compare=False)

    def predict(self, x: Sequence[float]) -> float:
        """P(y = 1) for one feature vector."""
        z = self.intercept
        for c, v in zip(self.coef, x, strict=True):
            z += c * v
        return sigmoid(z)

    def to_json(self) -> str:
        """Serialize to the JSON layout stored in ``state/models/``."""
        body = {
            "name": self.name,
            "features": list(self.features),
            "intercept": round(self.intercept, 6),
            "coef": {f: round(c, 6) for f, c in zip(self.features, self.coef, strict=True)},
            **self.info,
        }
        return json.dumps(body, indent=2) + "\n"

    @classmethod
    def load(cls, name: str, directory: Path = MODELS_DIR) -> LogisticModel:
        """Load ``<name>.json`` from the models directory."""
        d = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
        feats = tuple(d["features"])
        info = {k: v for k, v in d.items() if k not in ("name", "features", "intercept", "coef")}
        return cls(d["name"], feats, d["intercept"], tuple(d["coef"][f] for f in feats), info)


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting (a is small and dense)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        for r in range(col + 1, n):
            f = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


def fit_logistic(rows: Sequence[Sequence[float]], y: Sequence[float], l2: float = 1e-4, iters: int = 50) -> tuple[float, list[float]]:
    """Fit ``P(y=1|x) = sigmoid(b0 + b.x)``. Labels may be soft (in [0, 1]). Returns (intercept, coefs)."""
    k = len(rows[0]) + 1
    beta = [0.0] * k
    xs = [(1.0, *r) for r in rows]
    for _ in range(iters):
        grad = [0.0] * k
        hess = [[0.0] * k for _ in range(k)]
        for x, t in zip(xs, y, strict=True):
            p = sigmoid(sum(b * v for b, v in zip(beta, x, strict=True)))
            w = p * (1.0 - p)
            for i in range(k):
                grad[i] += (t - p) * x[i]
                for j in range(i, k):
                    hess[i][j] += w * x[i] * x[j]
        for i in range(k):
            for j in range(i):
                hess[i][j] = hess[j][i]
            if i:  # do not penalise the intercept
                hess[i][i] += l2
                grad[i] -= l2 * beta[i]
        step = _solve(hess, grad)
        beta = [b + s for b, s in zip(beta, step, strict=True)]
        if max(abs(s) for s in step) < 1e-9:
            break
    return beta[0], beta[1:]


def brier(p: Sequence[float], y: Sequence[float]) -> float:
    """Mean squared error between predictions and (possibly soft) labels."""
    return sum((a - b) ** 2 for a, b in zip(p, y, strict=True)) / len(p)


def expected_brier(p: Sequence[float], q: Sequence[float]) -> float:
    """Brier score expected when outcomes are Bernoulli(q): mean((p - q)^2 + q(1 - q))."""
    return sum((a - b) ** 2 + b * (1.0 - b) for a, b in zip(p, q, strict=True)) / len(p)


def calibration(p: Sequence[float], y: Sequence[float], bins: int = 5) -> list[tuple[int, float, float]]:
    """Equal-count bins sorted by prediction: (n, mean predicted, mean observed) per bin."""
    pairs = sorted(zip(p, y, strict=True))
    out = []
    for b in range(bins):
        chunk = pairs[b * len(pairs) // bins : (b + 1) * len(pairs) // bins]
        if chunk:
            out.append((len(chunk), sum(c[0] for c in chunk) / len(chunk), sum(c[1] for c in chunk) / len(chunk)))
    return out

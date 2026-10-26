"""Feature model, ensemble pooling, disagreement and evaluation metrics."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize
from scipy.special import softmax
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

OUTCOMES = ("home", "draw", "away")


class FeatureModel:
    """Multinomial logistic regression on time-correct difference features.

    An interpretable baseline: coefficients map directly to "how much does a one
    standard deviation change in feature X move the odds of each outcome".
    Gradient-boosted trees are deliberately not used by default; with a few
    thousand league matches and six features they do not beat a regularised
    linear model and are harder to calibrate and explain.
    """

    def __init__(self, c: float = 0.5) -> None:
        self.pipeline = make_pipeline(StandardScaler(), LogisticRegression(C=c, max_iter=1000))
        self.fitted = False

    def fit(self, x: np.ndarray, outcomes: np.ndarray) -> FeatureModel:
        """outcomes: 0 = home, 1 = draw, 2 = away."""
        if len(x) < 200 or len(set(outcomes.tolist())) < 3:
            raise ValueError("insufficient data to fit the feature model")
        self.pipeline.fit(x, outcomes)
        self.fitted = True
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        proba = self.pipeline.predict_proba(np.atleast_2d(x))
        classes = list(self.pipeline.classes_)
        return proba[:, [classes.index(i) for i in range(3)]]

    def coefficients(self, names: list[str]) -> dict[str, dict[str, float]]:
        lr: LogisticRegression = self.pipeline[-1]
        classes = list(lr.classes_)
        return {
            OUTCOMES[c]: {n: float(v) for n, v in zip(names, lr.coef_[classes.index(c)], strict=True)}
            for c in range(3)
        }


@dataclass
class LinearPool:
    """Weighted average of component probability vectors.

    Weights are learned only from out-of-sample (walk-forward) predictions, with a
    mild penalty toward equal weights so a short evaluation window cannot push a
    single component to 100%.
    """

    components: list[str]
    weights: np.ndarray = field(default_factory=lambda: np.array([]))
    penalty: float = 2.0

    def fit(self, preds: dict[str, np.ndarray], outcomes: np.ndarray) -> LinearPool:
        k = len(self.components)
        stack = np.stack([preds[c] for c in self.components])  # (k, n, classes)
        n = stack.shape[1]
        rows = np.arange(n)

        def loss(z: np.ndarray) -> float:
            w = softmax(z)
            p = np.tensordot(w, stack, axes=1)[rows, outcomes]
            return -float(np.log(np.clip(p, 1e-12, None)).mean()) + self.penalty / n * float(z @ z)

        res = minimize(loss, np.zeros(k), method="BFGS")
        self.weights = softmax(res.x)
        return self

    def combine(self, preds: dict[str, np.ndarray]) -> np.ndarray:
        available = [c for c in self.components if c in preds]
        if not available:
            raise ValueError("no components available to combine")
        w = np.array([self.weights[self.components.index(c)] for c in available])
        w = w / w.sum()
        return np.tensordot(w, np.stack([preds[c] for c in available]), axes=1)

    def to_dict(self) -> dict[str, float]:
        return {c: float(w) for c, w in zip(self.components, self.weights, strict=True)}


def disagreement(preds: dict[str, np.ndarray]) -> float:
    """Maximum pairwise total-variation distance between component distributions (0..1)."""
    names = list(preds)
    worst = 0.0
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            worst = max(worst, 0.5 * float(np.abs(preds[names[i]] - preds[names[j]]).sum()))
    return worst


# ------------------------------------------------------------------- metrics
def log_loss(probs: np.ndarray, outcomes: np.ndarray) -> float:
    p = probs[np.arange(len(outcomes)), outcomes]
    return -float(np.log(np.clip(p, 1e-12, None)).mean())


def brier(probs: np.ndarray, outcomes: np.ndarray) -> float:
    """Multi-class Brier score (sum over classes, averaged over matches; 0 is perfect)."""
    onehot = np.eye(probs.shape[1])[outcomes]
    return float(((probs - onehot) ** 2).sum(axis=1).mean())


def calibration_bins(p: np.ndarray, hit: np.ndarray, bins: int = 10) -> list[dict[str, float]]:
    """Reliability-diagram data for binary events: predicted mean vs observed frequency."""
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        mask = (p >= lo) & (p < hi if hi < 1 else p <= hi)
        if mask.sum() == 0:
            continue
        out.append({"lower": float(lo), "upper": float(hi), "predicted": float(p[mask].mean()),
                    "observed": float(hit[mask].mean()), "count": int(mask.sum())})
    return out


def expected_calibration_error(p: np.ndarray, hit: np.ndarray, bins: int = 10) -> float:
    b = calibration_bins(p, hit, bins)
    total = sum(x["count"] for x in b)
    return sum(x["count"] * abs(x["predicted"] - x["observed"]) for x in b) / total if total else float("nan")


def calibration_test(p: np.ndarray, hit: np.ndarray, bins: int = 10, sims: int = 500, seed: int = 0) -> dict:
    """Is the observed ECE larger than perfect calibration would produce by chance?

    Null distribution: outcomes simulated from the predicted probabilities
    themselves (i.e. a perfectly calibrated forecaster with the same forecasts).
    A fixed ECE threshold would ignore sample size; this test does not.
    """
    rng = np.random.default_rng(seed)
    observed = expected_calibration_error(p, hit, bins)
    null = np.array([expected_calibration_error(p, (rng.random(len(p)) < p).astype(int), bins) for _ in range(sims)])
    return {"ece": observed, "null_p95": float(np.percentile(null, 95)),
            "p_value": float((null >= observed).mean()), "n": int(len(p))}

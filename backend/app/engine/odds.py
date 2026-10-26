"""Bookmaker odds utilities: implied probabilities, overround, margin removal, EV.

All functions take decimal odds. Margin removal methods are approximations of the
bookmaker's "true" view; none of them fully removes favourite-longshot bias.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy.optimize import brentq


def implied_probability(decimal_odds: float) -> float:
    """Raw implied probability = 1 / decimal odds (includes bookmaker margin)."""
    if decimal_odds <= 1.0:
        raise ValueError(f"decimal odds must be > 1.0, got {decimal_odds}")
    return 1.0 / decimal_odds


def overround(odds: Sequence[float]) -> float:
    """Sum of raw implied probabilities minus 1 for a complete market (e.g. 0.05 = 5%)."""
    return float(sum(implied_probability(o) for o in odds) - 1.0)


def remove_margin_proportional(odds: Sequence[float]) -> list[float]:
    """Normalise raw implied probabilities so they sum to 1.

    This assumes the margin is spread proportionally across outcomes. In practice
    bookmakers tend to load more margin onto longshots, so this approximation
    slightly overstates longshot probabilities.
    """
    raw = np.array([implied_probability(o) for o in odds])
    return list(raw / raw.sum())


def remove_margin_shin(odds: Sequence[float]) -> list[float]:
    """Shin (1993) margin removal, which models insider trading and corrects
    part of the favourite-longshot bias. Falls back to proportional when the
    market has no positive overround."""
    raw = np.array([implied_probability(o) for o in odds])
    total = raw.sum()
    if total <= 1.0 + 1e-9:
        return list(raw / total)

    def probs(z: float) -> np.ndarray:
        return (np.sqrt(z**2 + 4 * (1 - z) * raw**2 / total) - z) / (2 * (1 - z))

    z = brentq(lambda z: probs(z).sum() - 1.0, 0.0, 0.4)
    p = probs(z)
    return list(p / p.sum())


def expected_value(probability: float, decimal_odds: float) -> float:
    """Expected profit per unit stake: p * odds - 1. Not a guarantee of profit."""
    return probability * decimal_odds - 1.0


def edge(probability: float, decimal_odds: float) -> float:
    """Estimated probability minus raw implied probability."""
    return probability - implied_probability(decimal_odds)


def asian_handicap_ev(
    p_win: float, p_half_win: float, p_push: float, p_half_loss: float, p_loss: float, odds: float
) -> float:
    """EV per unit stake for an Asian handicap selection with quarter-line outcomes."""
    total = p_win + p_half_win + p_push + p_half_loss + p_loss
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"AH outcome probabilities must sum to 1, got {total}")
    return (
        p_win * (odds - 1)
        + p_half_win * (odds - 1) / 2
        - p_half_loss * 0.5
        - p_loss * 1.0
    )

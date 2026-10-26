"""Joint scoreline distribution and the markets derived from it.

Every goal-based market probability is derived from one joint score matrix so the
markets are mutually consistent (e.g. P(home) + P(draw) + P(away) == 1).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import poisson

# Truncate the matrix far enough out that discarded mass is negligible (< 1e-6
# for any realistic rate); the residual is reported as `tail_mass`, then
# redistributed by renormalisation so no probability is silently dropped.
DEFAULT_MAX_GOALS = 10


def dixon_coles_tau(x: np.ndarray, y: np.ndarray, lam: float, mu: float, rho: float) -> np.ndarray:
    """Dixon-Coles low-score dependence correction factor."""
    tau = np.ones(np.broadcast(x, y).shape, dtype=float)
    tau = np.where((x == 0) & (y == 0), 1 - lam * mu * rho, tau)
    tau = np.where((x == 0) & (y == 1), 1 + lam * rho, tau)
    tau = np.where((x == 1) & (y == 0), 1 + mu * rho, tau)
    tau = np.where((x == 1) & (y == 1), 1 - rho, tau)
    return tau


@dataclass(frozen=True)
class ScoreMatrix:
    """probs[i, j] = P(home scores i, away scores j)."""

    probs: np.ndarray
    tail_mass: float
    home_rate: float
    away_rate: float

    @classmethod
    def from_rates(
        cls, home_rate: float, away_rate: float, rho: float = 0.0, max_goals: int = DEFAULT_MAX_GOALS
    ) -> ScoreMatrix:
        goals = np.arange(max_goals + 1)
        home = poisson.pmf(goals, home_rate)
        away = poisson.pmf(goals, away_rate)
        matrix = np.outer(home, away)
        x, y = np.meshgrid(goals, goals, indexing="ij")
        matrix = matrix * dixon_coles_tau(x, y, home_rate, away_rate, rho)
        matrix = np.clip(matrix, 0.0, None)
        tail = float(max(0.0, 1.0 - matrix.sum()))
        return cls(probs=matrix / matrix.sum(), tail_mass=tail, home_rate=home_rate, away_rate=away_rate)

    @property
    def _goal_diff(self) -> np.ndarray:
        n = self.probs.shape[0]
        i, j = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
        return i - j

    @property
    def _total(self) -> np.ndarray:
        n = self.probs.shape[0]
        i, j = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
        return i + j

    def one_x_two(self) -> dict[str, float]:
        gd = self._goal_diff
        return {
            "home": float(self.probs[gd > 0].sum()),
            "draw": float(self.probs[gd == 0].sum()),
            "away": float(self.probs[gd < 0].sum()),
        }

    def double_chance(self) -> dict[str, float]:
        r = self.one_x_two()
        return {"1X": r["home"] + r["draw"], "X2": r["draw"] + r["away"], "12": r["home"] + r["away"]}

    def draw_no_bet(self) -> dict[str, float]:
        """Probability of winning a DNB bet conditional on no draw (stake returned on draw)."""
        r = self.one_x_two()
        decisive = r["home"] + r["away"]
        return {"home": r["home"] / decisive, "away": r["away"] / decisive, "push": r["draw"]}

    def totals(self, line: float) -> dict[str, float]:
        """Over/under for half-goal lines (x.5). Whole lines would need push handling."""
        if line % 1 != 0.5:
            raise ValueError("only half-goal total lines are supported")
        over = float(self.probs[self._total > line].sum())
        return {"over": over, "under": 1.0 - over}

    def team_total(self, side: str, line: float) -> dict[str, float]:
        if line % 1 != 0.5:
            raise ValueError("only half-goal team total lines are supported")
        marginal = self.probs.sum(axis=1) if side == "home" else self.probs.sum(axis=0)
        over = float(marginal[np.arange(len(marginal)) > line].sum())
        return {"over": over, "under": 1.0 - over}

    def btts(self) -> dict[str, float]:
        no = float(self.probs[0, :].sum() + self.probs[:, 0].sum() - self.probs[0, 0])
        return {"yes": 1.0 - no, "no": no}

    def asian_handicap(self, home_line: float) -> dict[str, dict[str, float]]:
        """Outcome distribution for a home handicap line (e.g. -0.75), including quarter lines.

        Returns, for each side, probabilities of win / half_win / push / half_loss / loss.
        """
        if (home_line * 4) % 1 != 0:
            raise ValueError("AH lines must be multiples of 0.25")
        if (home_line * 4) % 2 != 0:  # quarter line: split stake across neighbouring lines
            parts = [home_line - 0.25, home_line + 0.25]
        else:
            parts = [home_line]
        home = self._ah_outcomes(parts)
        away = {
            "win": home["loss"], "half_win": home["half_loss"], "push": home["push"],
            "half_loss": home["half_win"], "loss": home["win"],
        }
        return {"home": home, "away": away}

    def _ah_outcomes(self, parts: list[float]) -> dict[str, float]:
        gd = self._goal_diff
        out = {"win": 0.0, "half_win": 0.0, "push": 0.0, "half_loss": 0.0, "loss": 0.0}
        n = self.probs.shape[0]
        for i in range(n):
            for j in range(n):
                p = self.probs[i, j]
                results = [np.sign(gd[i, j] + line) for line in parts]
                if len(results) == 1:
                    key = {1: "win", 0: "push", -1: "loss"}[int(results[0])]
                else:
                    score = sum(results)  # each half: +1 win, 0 push, -1 loss
                    key = {2: "win", 1: "half_win", 0: "push", -1: "half_loss", -2: "loss"}[int(score)]
                out[key] += float(p)
        return out

    def top_scorelines(self, n: int = 6) -> list[dict[str, float | int]]:
        flat = np.argsort(self.probs, axis=None)[::-1][:n]
        rows = []
        for idx in flat:
            i, j = np.unravel_index(idx, self.probs.shape)
            rows.append({"home": int(i), "away": int(j), "probability": float(self.probs[i, j])})
        return rows

    def grid(self, size: int = 6) -> dict[str, object]:
        """0..size-1 score grid for display plus the probability of any other score."""
        sub = self.probs[:size, :size]
        return {"matrix": sub.round(5).tolist(), "other": float(1.0 - sub.sum())}

    def all_markets(self) -> dict[str, object]:
        return {
            "1x2": self.one_x_two(),
            "double_chance": self.double_chance(),
            "draw_no_bet": self.draw_no_bet(),
            "totals": {str(line): self.totals(line) for line in (0.5, 1.5, 2.5, 3.5, 4.5)},
            "team_totals": {
                side: {str(line): self.team_total(side, line) for line in (0.5, 1.5, 2.5)}
                for side in ("home", "away")
            },
            "btts": self.btts(),
            "asian_handicap": {
                f"{line:+.2f}": self.asian_handicap(line)
                for line in (-2.5, -2.0, -1.5, -1.25, -1.0, -0.75, -0.5, -0.25, 0.0,
                             0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5)
            },
            "correct_score": self.top_scorelines(10),
            "expected_goals": {"home": self.home_rate, "away": self.away_rate},
            "tail_mass": self.tail_mass,
        }

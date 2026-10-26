"""Elo team-strength ratings (World Football Elo style) and an ordered-logit map to 1X2.

Ratings are kept per competition pool because teams in different divisions rarely
meet, so their ratings are not directly comparable. A team entering a pool
(promotion/relegation) starts at the pool mean plus `entry_offset`, or at its
previous rating in that pool regressed toward the mean.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit


@dataclass
class EloConfig:
    k: float = 20.0
    home_advantage: float = 65.0
    initial: float = 1500.0
    entry_offset: float = -60.0  # promoted teams tend to be weaker than the incumbents they join
    season_regression: float = 0.2  # fraction pulled to pool mean between seasons


@dataclass
class EloState:
    config: EloConfig = field(default_factory=EloConfig)
    ratings: dict[str, dict[str, float]] = field(default_factory=lambda: defaultdict(dict))
    last_season: dict[str, str] = field(default_factory=dict)
    first_season: dict[str, str] = field(default_factory=dict)
    games: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))

    def _pool_mean(self, pool: str) -> float:
        values = list(self.ratings[pool].values())
        return float(np.mean(values)) if values else self.config.initial

    def _entry_rating(self, pool: str, established: bool) -> float:
        return self._pool_mean(pool) + (self.config.entry_offset if established else 0.0)

    def rating(self, pool: str, team: str) -> float:
        if team not in self.ratings[pool]:
            # Only teams joining an established pool (promoted/relegated) get the offset;
            # in a pool's first observed season every team is new.
            established = self.last_season.get(pool) not in (None, self.first_season.get(pool))
            self.ratings[pool][team] = self._entry_rating(pool, established)
        return self.ratings[pool][team]

    def peek(self, pool: str, team: str, season: str | None = None) -> float:
        """Rating as it would be for a match in `season`, without mutating state
        (applies pending season regression and the entry rating virtually)."""
        last = self.last_season.get(pool)
        new_season = season is not None and last not in (None, season)
        established = new_season or last not in (None, self.first_season.get(pool))
        value = self.ratings[pool].get(team)
        if value is None:
            return self._entry_rating(pool, established)
        if new_season:
            value += self.config.season_regression * (self._pool_mean(pool) - value)
        return value

    def start_season(self, pool: str, season: str) -> None:
        if self.last_season.get(pool) not in (None, season):
            mean = self._pool_mean(pool)
            r = self.config.season_regression
            self.ratings[pool] = {t: v + r * (mean - v) for t, v in self.ratings[pool].items()}
        self.first_season.setdefault(pool, season)
        self.last_season[pool] = season

    def diff(self, pool: str, home: str, away: str, neutral: bool = False, season: str | None = None) -> float:
        """Rating difference home - away including home advantage (read-only)."""
        hfa = 0.0 if neutral else self.config.home_advantage
        return self.peek(pool, home, season) + hfa - self.peek(pool, away, season)

    def update(self, pool: str, home: str, away: str, home_goals: int, away_goals: int, neutral: bool = False) -> None:
        d = self.rating(pool, home) + (0.0 if neutral else self.config.home_advantage) - self.rating(pool, away)
        expected = 1.0 / (1.0 + 10 ** (-d / 400))
        actual = 1.0 if home_goals > away_goals else 0.5 if home_goals == away_goals else 0.0
        margin = abs(home_goals - away_goals)
        multiplier = 1.0 if margin <= 1 else 1.5 if margin == 2 else (11 + margin) / 8
        delta = self.config.k * multiplier * (actual - expected)
        self.ratings[pool][home] = self.rating(pool, home) + delta
        self.ratings[pool][away] = self.rating(pool, away) - delta
        self.games[(pool, home)] += 1
        self.games[(pool, away)] += 1


@dataclass
class OrderedLogit1X2:
    """P(away) = s(c1 - b*x), P(away or draw) = s(c2 - b*x), with x = elo diff / 400."""

    b: float = 1.0
    c1: float = -0.6
    c2: float = 0.6
    fitted: bool = False

    def fit(self, diffs: np.ndarray, outcomes: np.ndarray) -> OrderedLogit1X2:
        """outcomes: 0 = home win, 1 = draw, 2 = away win (project-wide encoding)."""
        if len(diffs) < 100:
            raise ValueError("need at least 100 matches to fit the Elo->1X2 map")
        x = np.asarray(diffs, float) / 400

        def nll(theta: np.ndarray) -> float:
            p = self._probs(x, theta[0], theta[1], theta[1] + math.exp(theta[2]))
            return -float(np.log(np.clip(p[np.arange(len(x)), outcomes], 1e-12, None)).sum())

        res = minimize(nll, np.array([1.0, -0.6, math.log(1.2)]), method="Nelder-Mead",
                       options={"maxiter": 2000, "xatol": 1e-6, "fatol": 1e-8})
        self.b, self.c1 = float(res.x[0]), float(res.x[1])
        self.c2 = self.c1 + math.exp(float(res.x[2]))
        self.fitted = True
        return self

    @staticmethod
    def _probs(x: np.ndarray, b: float, c1: float, c2: float) -> np.ndarray:
        p_away = expit(c1 - b * x)
        p_away_or_draw = expit(c2 - b * x)
        return np.column_stack([1 - p_away_or_draw, p_away_or_draw - p_away, p_away])

    def predict(self, diff: float) -> dict[str, float]:
        p = self._probs(np.array([diff / 400]), self.b, self.c1, self.c2)[0]
        return {"home": float(p[0]), "draw": float(p[1]), "away": float(p[2])}

    def to_dict(self) -> dict[str, float]:
        return {"b": self.b, "c1": self.c1, "c2": self.c2}


def season_of(d: date) -> str:
    """European season label, e.g. 2026-08-21 -> '2026-2027'. Season rolls over on 1 July."""
    start = d.year if d.month >= 7 else d.year - 1
    return f"{start}-{start + 1}"

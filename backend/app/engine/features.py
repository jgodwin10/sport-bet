"""Time-correct rolling team features.

`FeatureBuilder` walks matches in kickoff order. For every match it first emits the
features computed from the teams' *previous* matches and only afterwards absorbs
the match result. This makes leakage of the current or future results impossible
by construction, which the backtest tests assert explicitly.

To avoid counting the same evidence repeatedly, the supervised model uses a small
set of home-minus-away differences rather than many overlapping windows.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

WINDOW = 10
DECAY = 0.85  # per-match weight decay inside the window (most recent = 1)


@dataclass(frozen=True)
class MatchRecord:
    """A finished match with the statistics features are built from."""

    key: str
    kickoff: datetime
    pool: str
    home: str
    away: str
    home_goals: int
    away_goals: int
    home_shots_on_target: int | None = None
    away_shots_on_target: int | None = None
    home_xg: float | None = None
    away_xg: float | None = None


@dataclass
class _TeamGame:
    kickoff: datetime
    venue: str
    gf: int
    ga: int
    sotf: int | None
    sota: int | None
    xgf: float | None
    xga: float | None
    points: int


@dataclass
class FeatureBuilder:
    window: int = WINDOW
    history: dict[str, deque[_TeamGame]] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=40)))

    def _ewm(self, games: list[_TeamGame], attr: str) -> float | None:
        values = [(getattr(g, attr)) for g in games[-self.window :]]
        pairs = [(v, DECAY ** (len(values) - 1 - i)) for i, v in enumerate(values) if v is not None]
        if not pairs:
            return None
        return sum(v * w for v, w in pairs) / sum(w for _, w in pairs)

    def team_snapshot(self, team: str, at: datetime) -> dict[str, float | None]:
        games = [g for g in self.history[team] if g.kickoff < at]
        last = games[-1].kickoff if games else None
        return {
            "n": float(len(games)),
            "gf": self._ewm(games, "gf"),
            "ga": self._ewm(games, "ga"),
            "sotf": self._ewm(games, "sotf"),
            "sota": self._ewm(games, "sota"),
            "xgf": self._ewm(games, "xgf"),
            "xga": self._ewm(games, "xga"),
            "ppg": self._ewm(games, "points"),
            "rest_days": (at - last).total_seconds() / 86400 if last else None,
        }

    def features_for(self, home: str, away: str, kickoff: datetime) -> dict[str, float | None]:
        h = self.team_snapshot(home, kickoff)
        a = self.team_snapshot(away, kickoff)
        out: dict[str, float | None] = {"home_n": h["n"], "away_n": a["n"]}
        for k in ("gf", "ga", "sotf", "sota", "xgf", "xga", "ppg", "rest_days"):
            out[f"home_{k}"] = h[k]
            out[f"away_{k}"] = a[k]
        return out

    def absorb(self, m: MatchRecord) -> None:
        hp = 3 if m.home_goals > m.away_goals else 1 if m.home_goals == m.away_goals else 0
        ap = 3 if m.away_goals > m.home_goals else 1 if m.home_goals == m.away_goals else 0
        self.history[m.home].append(_TeamGame(m.kickoff, "H", m.home_goals, m.away_goals,
                                              m.home_shots_on_target, m.away_shots_on_target,
                                              m.home_xg, m.away_xg, hp))
        self.history[m.away].append(_TeamGame(m.kickoff, "A", m.away_goals, m.home_goals,
                                              m.away_shots_on_target, m.home_shots_on_target,
                                              m.away_xg, m.home_xg, ap))


# Inputs to the supervised model, all home-minus-away differences.
MODEL_FEATURES = ["elo_diff", "gf_diff", "ga_diff", "sot_diff", "ppg_diff", "rest_diff"]


def model_vector(raw: dict[str, float | None], elo_diff: float, league_avg_goals: float) -> np.ndarray:
    """Convert raw snapshot features into the model's numeric vector.

    Missing values (e.g. no prior games for a promoted team) are replaced by
    neutral league-average values; the caller separately reduces reliability for
    low sample sizes rather than pretending the value is known.
    """

    def val(key: str, default: float) -> float:
        v = raw.get(key)
        return default if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)

    g = league_avg_goals / 2
    sot_default = 4.0
    return np.array([
        elo_diff / 100,
        val("home_gf", g) - val("away_gf", g),
        val("home_ga", g) - val("away_ga", g),
        val("home_sotf", sot_default) - val("away_sotf", sot_default)
        - (val("home_sota", sot_default) - val("away_sota", sot_default)),
        val("home_ppg", 1.35) - val("away_ppg", 1.35),
        min(val("home_rest_days", 7), 14) - min(val("away_rest_days", 7), 14),
    ])

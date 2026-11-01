"""Model suite shared by live predictions and the walk-forward backtest.

Usage:
    suite = ModelSuite(config)
    for record in finished_matches_in_kickoff_order:   # all strictly before cutoff
        suite.absorb(record)
    suite.refit(cutoff)
    out = suite.components(home, away, kickoff)

`refit` refuses to run if any absorbed match kicked off at or after the cutoff,
so leakage of future results is structurally prevented.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from app.engine.dixon_coles import DixonColesModel, MatchObservation, UnknownTeamError
from app.engine.elo import EloConfig, EloState, OrderedLogit1X2, season_of
from app.engine.ensemble import LOG_POOL_MARKER, FeatureModel, LinearPool, LogPool, disagreement
from app.engine.features import MODEL_FEATURES, FeatureBuilder, MatchRecord, model_vector
from app.engine.odds import remove_margin_shin
from app.engine.scoreline import ScoreMatrix

log = logging.getLogger(__name__)

COMPONENTS_1X2 = ["dixon_coles", "elo", "feature_model", "market"]
STAT_COMPONENTS = ["dixon_coles", "elo", "feature_model"]


@dataclass
class SuiteConfig:
    dc_half_life_days: float = 240.0
    dc_ridge: float = 2.0
    dc_lookback_days: int = 3 * 365
    max_goals: int = 10
    min_prior_games_for_training: int = 3
    compute_intervals: bool = True
    elo: EloConfig = field(default_factory=EloConfig)


def outcome_index(home_goals: int, away_goals: int) -> int:
    return 0 if home_goals > away_goals else 1 if home_goals == away_goals else 2


@dataclass
class ComponentOutput:
    matrix: ScoreMatrix | None
    one_x_two: dict[str, np.ndarray]  # component -> [home, draw, away]
    raw_features: dict[str, float | None]
    feature_vector: list[float]
    elo: dict[str, float]
    dc_team_params: dict[str, float] | None
    sample_sizes: dict[str, int]
    intervals: dict[str, tuple[float, float]] | None
    missing_components: list[str]


class ModelSuite:
    def __init__(self, config: SuiteConfig | None = None, pool: str = "default") -> None:
        self.config = config or SuiteConfig()
        self.pool = pool
        self.elo = EloState(self.config.elo)
        self.features = FeatureBuilder()
        self.history: list[MatchRecord] = []
        self._elo_rows: list[tuple[float, int]] = []
        self._feature_rows: list[tuple[np.ndarray, int]] = []
        self.dc: DixonColesModel | None = None
        self.elo_map: OrderedLogit1X2 | None = None
        self.feature_model: FeatureModel | None = None
        self.cutoff: datetime | None = None
        self.fit_errors: dict[str, str] = {}

    # ------------------------------------------------------------- learning
    def absorb(self, rec: MatchRecord) -> None:
        if self.history and rec.kickoff < self.history[-1].kickoff:
            raise ValueError("matches must be absorbed in kickoff order")
        self.elo.start_season(self.pool, season_of(rec.kickoff.date()))
        diff = self.elo.diff(self.pool, rec.home, rec.away)
        outcome = outcome_index(rec.home_goals, rec.away_goals)
        raw = self.features.features_for(rec.home, rec.away, rec.kickoff)
        if min(raw["home_n"] or 0, raw["away_n"] or 0) >= self.config.min_prior_games_for_training:
            self._feature_rows.append((model_vector(raw, diff, self._league_avg()), outcome))
        self._elo_rows.append((diff, outcome))
        self.elo.update(self.pool, rec.home, rec.away, rec.home_goals, rec.away_goals)
        self.features.absorb(rec)
        self.history.append(rec)

    def _league_avg(self) -> float:
        recent = self.history[-380:]
        if not recent:
            return 2.6
        return float(np.mean([r.home_goals + r.away_goals for r in recent]))

    def refit(self, cutoff: datetime) -> None:
        if self.history and self.history[-1].kickoff >= cutoff:
            raise ValueError("absorbed matches at or after the cutoff: refusing to fit (leakage)")
        self.cutoff = cutoff
        self.fit_errors = {}
        start = cutoff - timedelta(days=self.config.dc_lookback_days)
        obs = [MatchObservation(r.home, r.away, r.home_goals, r.away_goals, r.kickoff.date())
               for r in self.history if r.kickoff >= start]
        dc = DixonColesModel(self.config.dc_half_life_days, self.config.dc_ridge, self.config.max_goals)
        try:
            dc.fit(obs, as_of=cutoff.date() + timedelta(days=1), compute_covariance=self.config.compute_intervals)
            self.dc = dc
        except (ValueError, RuntimeError) as exc:
            self.dc, self.fit_errors["dixon_coles"] = None, str(exc)
        try:
            diffs = np.array([d for d, _ in self._elo_rows])
            outcomes = np.array([o for _, o in self._elo_rows])
            self.elo_map = OrderedLogit1X2().fit(diffs, outcomes)
        except ValueError as exc:
            self.elo_map, self.fit_errors["elo"] = None, str(exc)
        try:
            x = np.array([v for v, _ in self._feature_rows])
            y = np.array([o for _, o in self._feature_rows])
            self.feature_model = FeatureModel().fit(x, y)
        except ValueError as exc:
            self.feature_model, self.fit_errors["feature_model"] = None, str(exc)

    # ----------------------------------------------------------- prediction
    def components(self, home: str, away: str, kickoff: datetime, neutral: bool = False,
                   with_intervals: bool | None = None) -> ComponentOutput:
        if self.cutoff is None:
            raise RuntimeError("call refit() first")
        missing: list[str] = []
        probs: dict[str, np.ndarray] = {}
        matrix, team_params, intervals = None, None, None
        n_matches = {}
        if self.dc is not None:
            try:
                matrix = self.dc.predict(home, away, neutral)
                r = matrix.one_x_two()
                probs["dixon_coles"] = np.array([r["home"], r["draw"], r["away"]])
                p = self.dc.params
                idx = p.index
                team_params = {
                    "home_attack": float(np.exp(p.attack[idx[home]])),
                    "home_defence": float(np.exp(p.defence[idx[home]])),
                    "away_attack": float(np.exp(p.attack[idx[away]])),
                    "away_defence": float(np.exp(p.defence[idx[away]])),
                    "home_advantage": float(np.exp(p.home_advantage)),
                    "rho": p.rho,
                }
                n_matches = {"home": p.n_matches.get(home, 0), "away": p.n_matches.get(away, 0)}
                use_intervals = self.config.compute_intervals if with_intervals is None else with_intervals
                if use_intervals:
                    intervals = self.dc.predictive_intervals(home, away, neutral)
            except UnknownTeamError as exc:
                missing.append(f"dixon_coles: no match history for {exc.args[0]}")
        else:
            missing.append(f"dixon_coles: {self.fit_errors.get('dixon_coles', 'not fitted')}")

        diff = self.elo.diff(self.pool, home, away, neutral, season=season_of(kickoff.date()))
        if self.elo_map is not None:
            e = self.elo_map.predict(diff)
            probs["elo"] = np.array([e["home"], e["draw"], e["away"]])
        else:
            missing.append(f"elo: {self.fit_errors.get('elo', 'not fitted')}")

        raw = self.features.features_for(home, away, kickoff)
        vec = model_vector(raw, diff, self._league_avg())
        if self.feature_model is not None:
            probs["feature_model"] = self.feature_model.predict(vec)[0]
        else:
            missing.append(f"feature_model: {self.fit_errors.get('feature_model', 'not fitted')}")

        return ComponentOutput(
            matrix=matrix, one_x_two=probs, raw_features=raw,
            feature_vector=[float(v) for v in vec],
            elo={"home": self.elo.peek(self.pool, home, season_of(kickoff.date())),
                 "away": self.elo.peek(self.pool, away, season_of(kickoff.date())), "diff": diff},
            dc_team_params=team_params,
            sample_sizes={"home": int(n_matches.get("home", raw["home_n"] or 0)),
                          "away": int(n_matches.get("away", raw["away_n"] or 0))},
            intervals=intervals, missing_components=missing,
        )


# ------------------------------------------------------------- combination
def market_1x2(prices: dict[str, float] | None) -> np.ndarray | None:
    """Margin-removed (Shin) market probabilities from a {home, draw, away} price set."""
    if not prices or any(k not in prices for k in ("home", "draw", "away")):
        return None
    return np.array(remove_margin_shin([prices["home"], prices["draw"], prices["away"]]))


def market_binary(over: float | None, under: float | None) -> float | None:
    if not over or not under:
        return None
    return remove_margin_shin([over, under])[0]


def combine_1x2(probs: dict[str, np.ndarray], weights: dict[str, float] | None) -> tuple[np.ndarray, dict[str, float]]:
    """Pool with learned weights; equal-weight linear pool over statistical models if unvalidated.

    Versions learned since the log pool was introduced carry LOG_POOL_MARKER; older
    deployed versions keep the linear pool their weights were learned for. The
    returned weights are each component's share of the total, for display.
    """
    if weights and LOG_POOL_MARKER in weights:
        pool = LogPool.from_dict(weights)
        used = {c: w for c, w in zip(pool.components, pool.weights, strict=True) if c in probs}
        total = sum(used.values())
        shares = {c: w / total for c, w in used.items()} if total else {c: 1 / len(used) for c in used}
        return pool.combine(probs), shares
    weights = {k: v for k, v in (weights or {}).items() if not k.startswith("_")}
    if weights:
        pool = LinearPool(list(weights), np.array(list(weights.values())))
        used = {c: w for c, w in weights.items() if c in probs}
    else:
        stat = [c for c in STAT_COMPONENTS if c in probs]
        pool = LinearPool(stat, np.full(len(stat), 1 / max(len(stat), 1)))
        used = {c: 1 / len(stat) for c in stat}
    total = sum(used.values())
    return pool.combine(probs), {c: w / total for c, w in used.items()}


def stat_disagreement(probs: dict[str, np.ndarray]) -> float | None:
    stat = {c: p for c, p in probs.items() if c in STAT_COMPONENTS}
    return disagreement(stat) if len(stat) >= 2 else None


def rake_matrix(matrix: ScoreMatrix, one_x_two: np.ndarray, over_25: float | None = None,
                iterations: int = 50) -> ScoreMatrix:
    """Adjust the score matrix (iterative proportional fitting) so its 1X2 (and
    optionally over 2.5) margins equal the ensemble's, keeping every derived
    market (AH, correct score, BTTS) consistent with the headline probabilities."""
    p = matrix.probs.copy()
    n = p.shape[0]
    i, j = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    regions = [(i > j), (i == j), (i < j)]
    totals = [(i + j) > 2.5, (i + j) < 2.5]
    for _ in range(iterations):
        for mask, target in zip(regions, one_x_two, strict=True):
            s = p[mask].sum()
            if s > 0:
                p[mask] *= target / s
        if over_25 is not None:
            for mask, target in zip(totals, (over_25, 1 - over_25), strict=True):
                s = p[mask].sum()
                if s > 0:
                    p[mask] *= target / s
    return ScoreMatrix(probs=p / p.sum(), tail_mass=matrix.tail_mass, home_rate=matrix.home_rate,
                       away_rate=matrix.away_rate)


__all__ = ["MODEL_FEATURES", "COMPONENTS_1X2", "ModelSuite", "SuiteConfig", "combine_1x2", "market_1x2",
           "market_binary", "rake_matrix", "stat_disagreement", "outcome_index"]

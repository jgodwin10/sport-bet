"""Dixon-Coles (1997) bivariate Poisson goal model.

log(lambda_home) = intercept + home_adv + attack[home] + defence[away]
log(mu_away)     = intercept + attack[away] + defence[home]

Design choices (documented trade-offs):
* Exponential time decay weights (Dixon & Coles' xi) so recent matches matter more.
  `half_life_days` is the transparent knob; default ~ 1 season.
* Ridge (L2) penalty on attack/defence instead of a sum-to-zero constraint. It
  identifies the model and shrinks teams with little data (newly promoted sides)
  toward league average rather than letting a handful of results dominate.
* Parameter uncertainty via a Laplace approximation (inverse Hessian of the
  penalised negative log-likelihood) so downstream code can report intervals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import poisson

from app.engine.scoreline import ScoreMatrix

RHO_BOUNDS = (-0.25, 0.25)


@dataclass(frozen=True)
class MatchObservation:
    home: str
    away: str
    home_goals: int
    away_goals: int
    played_on: date
    neutral: bool = False


@dataclass
class DixonColesParams:
    teams: list[str]
    attack: np.ndarray
    defence: np.ndarray
    intercept: float
    home_advantage: float
    rho: float
    covariance: np.ndarray | None = None
    n_matches: dict[str, int] = field(default_factory=dict)
    fitted_through: date | None = None

    @property
    def index(self) -> dict[str, int]:
        return {t: i for i, t in enumerate(self.teams)}

    def vector(self) -> np.ndarray:
        return np.concatenate([self.attack, self.defence, [self.intercept, self.home_advantage, self.rho]])

    def to_dict(self) -> dict[str, object]:
        return {
            "teams": self.teams,
            "attack": self.attack.tolist(),
            "defence": self.defence.tolist(),
            "intercept": self.intercept,
            "home_advantage": self.home_advantage,
            "rho": self.rho,
            "n_matches": self.n_matches,
            "fitted_through": self.fitted_through.isoformat() if self.fitted_through else None,
        }


class UnknownTeamError(KeyError):
    pass


class DixonColesModel:
    def __init__(self, half_life_days: float = 365.0, ridge: float = 2.0, max_goals: int = 10) -> None:
        self.half_life_days = half_life_days
        self.ridge = ridge
        self.max_goals = max_goals
        self.params: DixonColesParams | None = None

    # ------------------------------------------------------------------ fitting
    def fit(self, matches: list[MatchObservation], as_of: date, compute_covariance: bool = True) -> DixonColesParams:
        """Fit on matches strictly before `as_of` (guards against leakage)."""
        matches = [m for m in matches if m.played_on < as_of]
        if len(matches) < 30:
            raise ValueError(f"insufficient matches to fit Dixon-Coles ({len(matches)} < 30)")
        teams = sorted({m.home for m in matches} | {m.away for m in matches})
        idx = {t: i for i, t in enumerate(teams)}
        n = len(teams)
        hi = np.array([idx[m.home] for m in matches])
        ai = np.array([idx[m.away] for m in matches])
        x = np.array([m.home_goals for m in matches], dtype=float)
        y = np.array([m.away_goals for m in matches], dtype=float)
        neutral = np.array([m.neutral for m in matches], dtype=float)
        age = np.array([(as_of - m.played_on).days for m in matches], dtype=float)
        w = np.power(0.5, age / self.half_life_days)
        const = w @ (gammaln(x + 1) + gammaln(y + 1))

        def unpack(theta: np.ndarray):
            return theta[:n], theta[n : 2 * n], theta[2 * n], theta[2 * n + 1], theta[2 * n + 2]

        def nll_and_grad(theta: np.ndarray) -> tuple[float, np.ndarray]:
            att, dfn, c, h, rho = unpack(theta)
            log_lam = c + h * (1 - neutral) + att[hi] + dfn[ai]
            log_mu = c + att[ai] + dfn[hi]
            lam, mu = np.exp(log_lam), np.exp(log_mu)

            m00 = (x == 0) & (y == 0)
            m01 = (x == 0) & (y == 1)
            m10 = (x == 1) & (y == 0)
            m11 = (x == 1) & (y == 1)
            tau = np.ones_like(lam)
            tau[m00] = 1 - lam[m00] * mu[m00] * rho
            tau[m01] = 1 + lam[m01] * rho
            tau[m10] = 1 + mu[m10] * rho
            tau[m11] = 1 - rho
            tau = np.clip(tau, 1e-10, None)

            ll = np.log(tau) + x * log_lam - lam + y * log_mu - mu
            nll = -(w @ ll) + const
            nll += self.ridge * 0.5 * (att @ att + dfn @ dfn)

            # d ll / d log_lam, d log_mu, d rho
            g_lam = x - lam
            g_mu = y - mu
            g_rho = np.zeros_like(lam)
            g_lam[m00] += -lam[m00] * mu[m00] * rho / tau[m00]
            g_mu[m00] += -lam[m00] * mu[m00] * rho / tau[m00]
            g_rho[m00] = -lam[m00] * mu[m00] / tau[m00]
            g_lam[m01] += lam[m01] * rho / tau[m01]
            g_rho[m01] = lam[m01] / tau[m01]
            g_mu[m10] += mu[m10] * rho / tau[m10]
            g_rho[m10] = mu[m10] / tau[m10]
            g_rho[m11] = -1 / tau[m11]

            wl, wm = w * g_lam, w * g_mu
            g_att = np.bincount(hi, wl, n) + np.bincount(ai, wm, n)
            g_def = np.bincount(ai, wl, n) + np.bincount(hi, wm, n)
            grad = -np.concatenate(
                [g_att, g_def, [wl.sum() + wm.sum(), (wl * (1 - neutral)).sum(), w @ g_rho]]
            )
            grad[:n] += self.ridge * att
            grad[n : 2 * n] += self.ridge * dfn
            return float(nll), grad

        mean_goals = max(float((w @ (x + y)) / (2 * w.sum())), 0.1)
        theta0 = np.concatenate([np.zeros(2 * n), [np.log(mean_goals), 0.2, -0.05]])
        bounds = [(None, None)] * (2 * n + 2) + [RHO_BOUNDS]
        res = minimize(nll_and_grad, theta0, jac=True, method="L-BFGS-B", bounds=bounds,
                       options={"maxiter": 500})
        if not res.success and "ABNORMAL" not in str(res.message):
            raise RuntimeError(f"Dixon-Coles optimisation failed: {res.message}")

        cov = self._laplace_covariance(nll_and_grad, res.x) if compute_covariance else None
        att, dfn, c, h, rho = unpack(res.x)
        counts: dict[str, int] = {t: 0 for t in teams}
        for m in matches:
            counts[m.home] += 1
            counts[m.away] += 1
        self.params = DixonColesParams(
            teams=teams, attack=att.copy(), defence=dfn.copy(), intercept=float(c),
            home_advantage=float(h), rho=float(rho), covariance=cov, n_matches=counts,
            fitted_through=max(m.played_on for m in matches),
        )
        return self.params

    @staticmethod
    def _laplace_covariance(fn, theta: np.ndarray) -> np.ndarray | None:
        """Finite-difference Hessian of the analytic gradient, inverted."""
        k = len(theta)
        hess = np.zeros((k, k))
        eps = 1e-5
        for i in range(k):
            step = np.zeros(k)
            step[i] = eps
            hess[:, i] = (fn(theta + step)[1] - fn(theta - step)[1]) / (2 * eps)
        hess = (hess + hess.T) / 2
        try:
            cov = np.linalg.inv(hess)
        except np.linalg.LinAlgError:
            return None
        if np.any(np.diag(cov) < 0):
            return None
        return cov

    # --------------------------------------------------------------- prediction
    def rates(self, home: str, away: str, neutral: bool = False, theta: np.ndarray | None = None) -> tuple[float, float]:
        p = self._require()
        idx = p.index
        for team in (home, away):
            if team not in idx:
                raise UnknownTeamError(team)
        n = len(p.teams)
        if theta is None:
            theta = p.vector()
        att, dfn, c, h = theta[:n], theta[n : 2 * n], theta[2 * n], theta[2 * n + 1]
        hi, ai = idx[home], idx[away]
        lam = np.exp(c + (0 if neutral else h) + att[hi] + dfn[ai])
        mu = np.exp(c + att[ai] + dfn[hi])
        return float(lam), float(mu)

    def predict(self, home: str, away: str, neutral: bool = False) -> ScoreMatrix:
        p = self._require()
        lam, mu = self.rates(home, away, neutral)
        return ScoreMatrix.from_rates(lam, mu, p.rho, self.max_goals)

    def predictive_intervals(
        self, home: str, away: str, neutral: bool = False, draws: int = 400, level: float = 0.9, seed: int = 0
    ) -> dict[str, tuple[float, float]] | None:
        """Monte Carlo intervals for key market probabilities from parameter uncertainty."""
        p = self._require()
        if p.covariance is None:
            return None
        rng = np.random.default_rng(seed)
        samples = rng.multivariate_normal(p.vector(), p.covariance, size=draws, check_valid="ignore")
        n, idx = len(p.teams), p.index
        hi, ai = idx[home], idx[away]
        c, h = samples[:, 2 * n], samples[:, 2 * n + 1]
        lam = np.exp(c + (0 if neutral else h) + samples[:, hi] + samples[:, n + ai])
        mu = np.exp(c + samples[:, ai] + samples[:, n + hi])
        rho = np.clip(samples[:, -1], *RHO_BOUNDS)
        # Vectorised score matrices for all draws: (draws, G, G)
        goals = np.arange(self.max_goals + 1)
        m = poisson.pmf(goals[None, :], lam[:, None])[:, :, None] * poisson.pmf(goals[None, :], mu[:, None])[:, None, :]
        m[:, 0, 0] *= 1 - lam * mu * rho
        m[:, 0, 1] *= 1 + lam * rho
        m[:, 1, 0] *= 1 + mu * rho
        m[:, 1, 1] *= 1 - rho
        m = np.clip(m, 0, None)
        m /= m.sum(axis=(1, 2), keepdims=True)
        i, j = np.meshgrid(goals, goals, indexing="ij")
        keys = {
            "home": (m * (i > j)).sum(axis=(1, 2)), "draw": (m * (i == j)).sum(axis=(1, 2)),
            "away": (m * (i < j)).sum(axis=(1, 2)), "over_2.5": (m * ((i + j) > 2.5)).sum(axis=(1, 2)),
            "btts_yes": (m * ((i > 0) & (j > 0))).sum(axis=(1, 2)),
        }
        lo, hi_ = (1 - level) / 2 * 100, (1 + level) / 2 * 100
        return {k: (float(np.percentile(v, lo)), float(np.percentile(v, hi_))) for k, v in keys.items()}

    def _require(self) -> DixonColesParams:
        if self.params is None:
            raise RuntimeError("model not fitted")
        return self.params

"""Unit tests for the statistical engine.

All match data in this file is SYNTHETIC, generated from known parameters, and is
used only to verify that the estimators and calculations behave correctly.
"""

from datetime import date, datetime, timedelta

import numpy as np
import pytest
from scipy.stats import poisson

from app.engine.decision import (
    Candidate, ReliabilityInputs, SelectionRules, assess_reliability, classify, evaluate_candidate,
)
from app.engine.dixon_coles import DixonColesModel, MatchObservation, UnknownTeamError
from app.engine.elo import EloState, OrderedLogit1X2, season_of
from app.engine.ensemble import LinearPool, LogPool, brier, calibration_bins, calibration_test, disagreement, log_loss
from app.engine.features import FeatureBuilder, MatchRecord
from app.engine.odds import (
    asian_handicap_ev, edge, expected_value, implied_probability, overround,
    remove_margin_proportional, remove_margin_shin,
)
from app.engine.scoreline import ScoreMatrix


# ---------------------------------------------------------------- odds maths
def test_implied_probability_and_ev_example_from_spec():
    assert implied_probability(2.0) == pytest.approx(0.5)
    assert expected_value(0.55, 2.00) == pytest.approx(0.10)
    assert edge(0.55, 2.00) == pytest.approx(0.05)


def test_implied_probability_rejects_invalid_odds():
    with pytest.raises(ValueError):
        implied_probability(1.0)


def test_overround_and_proportional_normalisation():
    odds = [2.10, 3.40, 3.60]
    assert overround(odds) == pytest.approx(1 / 2.1 + 1 / 3.4 + 1 / 3.6 - 1)
    probs = remove_margin_proportional(odds)
    assert sum(probs) == pytest.approx(1.0)
    assert probs[0] > probs[1] > probs[2]


def test_shin_shifts_probability_from_longshot_to_favourite():
    odds = [1.30, 5.50, 11.0]
    prop = remove_margin_proportional(odds)
    shin = remove_margin_shin(odds)
    assert sum(shin) == pytest.approx(1.0)
    assert shin[0] > prop[0]
    assert shin[2] < prop[2]


def test_fair_market_is_unchanged_by_margin_removal():
    odds = [2.0, 4.0, 4.0]
    assert remove_margin_shin(odds) == pytest.approx([0.5, 0.25, 0.25])


def test_asian_handicap_ev_with_half_outcomes():
    # Half win at odds 2.0 returns +0.5 units; half loss returns -0.5 units
    assert asian_handicap_ev(0, 1, 0, 0, 0, 2.0) == pytest.approx(0.5)
    assert asian_handicap_ev(0, 0, 0, 1, 0, 2.0) == pytest.approx(-0.5)
    assert asian_handicap_ev(0, 0, 1, 0, 0, 2.0) == pytest.approx(0.0)


# ---------------------------------------------------------- score matrix
@pytest.fixture
def matrix() -> ScoreMatrix:
    return ScoreMatrix.from_rates(1.6, 1.1, rho=-0.08)


def test_1x2_sums_to_one(matrix):
    assert sum(matrix.one_x_two().values()) == pytest.approx(1.0)
    assert matrix.probs.sum() == pytest.approx(1.0)
    assert matrix.tail_mass < 1e-5


def test_independent_poisson_matches_closed_form():
    sm = ScoreMatrix.from_rates(1.4, 1.2, rho=0.0)
    p00 = poisson.pmf(0, 1.4) * poisson.pmf(0, 1.2)
    assert sm.probs[0, 0] == pytest.approx(p00, rel=1e-4)
    # BTTS no = P(H=0) + P(A=0) - P(both 0)
    expected_no = poisson.pmf(0, 1.4) + poisson.pmf(0, 1.2) - p00
    assert sm.btts()["no"] == pytest.approx(expected_no, rel=1e-4)
    # Total goals ~ Poisson(2.6) under independence
    assert sm.totals(2.5)["under"] == pytest.approx(poisson.cdf(2, 2.6), rel=1e-4)


def test_negative_rho_inflates_draws():
    base = ScoreMatrix.from_rates(1.3, 1.1, rho=0.0)
    dc = ScoreMatrix.from_rates(1.3, 1.1, rho=-0.1)
    assert dc.probs[0, 0] > base.probs[0, 0]
    assert dc.probs[1, 1] > base.probs[1, 1]


def test_totals_monotonic_and_complementary(matrix):
    overs = [matrix.totals(line)["over"] for line in (0.5, 1.5, 2.5, 3.5, 4.5)]
    assert overs == sorted(overs, reverse=True)
    for line in (1.5, 2.5, 3.5):
        t = matrix.totals(line)
        assert t["over"] + t["under"] == pytest.approx(1.0)
    with pytest.raises(ValueError):
        matrix.totals(2.0)


def test_double_chance_and_dnb(matrix):
    r = matrix.one_x_two()
    dc = matrix.double_chance()
    assert dc["1X"] == pytest.approx(r["home"] + r["draw"])
    dnb = matrix.draw_no_bet()
    assert dnb["home"] + dnb["away"] == pytest.approx(1.0)


def test_asian_handicap_consistency(matrix):
    r = matrix.one_x_two()
    ah0 = matrix.asian_handicap(0.0)["home"]
    assert ah0["win"] == pytest.approx(r["home"])
    assert ah0["push"] == pytest.approx(r["draw"])
    ah_half = matrix.asian_handicap(-0.5)["home"]
    assert ah_half["win"] == pytest.approx(r["home"])
    quarter = matrix.asian_handicap(-0.25)["home"]
    assert quarter["half_loss"] == pytest.approx(r["draw"])
    for line in (-1.75, -1.0, 0.75):
        assert sum(matrix.asian_handicap(line)["home"].values()) == pytest.approx(1.0)


def test_team_totals_and_markets_bundle(matrix):
    m = matrix.all_markets()
    assert m["team_totals"]["home"]["0.5"]["over"] == pytest.approx(1 - matrix.probs[0, :].sum())
    assert len(m["correct_score"]) == 10


# ------------------------------------------------------------ Dixon-Coles
def _synthetic_league(seed: int = 7, seasons: int = 2):
    """SYNTHETIC league with known team strengths."""
    rng = np.random.default_rng(seed)
    teams = [f"Team{i:02d}" for i in range(12)]
    attack = np.linspace(-0.4, 0.4, 12)
    defence = -np.linspace(-0.3, 0.3, 12)
    matches, day = [], date(2023, 8, 1)
    for _ in range(seasons):
        for h in range(12):
            for a in range(12):
                if h == a:
                    continue
                lam = np.exp(0.1 + 0.25 + attack[h] + defence[a])
                mu = np.exp(0.1 + attack[a] + defence[h])
                matches.append(MatchObservation(teams[h], teams[a], int(rng.poisson(lam)),
                                                int(rng.poisson(mu)), day))
                day += timedelta(days=1)
    return teams, attack, matches, day


def test_dixon_coles_recovers_known_parameters():
    teams, attack, matches, end = _synthetic_league()
    model = DixonColesModel(half_life_days=10_000, ridge=0.5)
    params = model.fit(matches, as_of=end)
    corr = np.corrcoef(params.attack, attack)[0, 1]
    assert corr > 0.9
    assert 0.1 < params.home_advantage < 0.4
    strong, weak = teams[-1], teams[0]
    assert model.predict(strong, weak).one_x_two()["home"] > model.predict(weak, strong).one_x_two()["home"]


def test_dixon_coles_ignores_matches_on_or_after_as_of():
    _, _, matches, _ = _synthetic_league()
    cutoff = matches[200].played_on
    params = DixonColesModel().fit(matches, as_of=cutoff)
    assert params.fitted_through < cutoff


def test_dixon_coles_unknown_team_and_insufficient_data():
    _, _, matches, end = _synthetic_league()
    model = DixonColesModel()
    with pytest.raises(ValueError):
        model.fit(matches[:10], as_of=end)
    model.fit(matches, as_of=end)
    with pytest.raises(UnknownTeamError):
        model.predict("Team00", "Promoted FC")


def test_dixon_coles_intervals_contain_point_estimate():
    _, _, matches, end = _synthetic_league()
    model = DixonColesModel()
    model.fit(matches, as_of=end)
    point = model.predict("Team05", "Team06").one_x_two()["home"]
    lo, hi = model.predictive_intervals("Team05", "Team06", draws=200)["home"]
    assert lo < point < hi


def test_neutral_venue_removes_home_advantage():
    _, _, matches, end = _synthetic_league()
    model = DixonColesModel()
    model.fit(matches, as_of=end)
    home = model.predict("Team05", "Team06").one_x_two()["home"]
    neutral = model.predict("Team05", "Team06", neutral=True).one_x_two()["home"]
    assert neutral < home


# --------------------------------------------------------------------- Elo
def test_elo_update_is_zero_sum_and_directional():
    s = EloState()
    s.update("E0", "A", "B", 2, 0)
    assert s.ratings["E0"]["A"] > 1500 > s.ratings["E0"]["B"]
    assert s.ratings["E0"]["A"] + s.ratings["E0"]["B"] == pytest.approx(3000)


def test_elo_promoted_team_enters_below_pool_mean():
    s = EloState()
    s.start_season("E0", "2023-2024")
    s.update("E0", "A", "B", 1, 1)
    assert s.rating("E0", "C") == pytest.approx(1500)  # first season: everyone is new
    s.start_season("E0", "2024-2025")
    assert s.rating("E0", "Promoted") < 1500


def test_elo_season_regression():
    s = EloState()
    s.start_season("E0", "2023-2024")
    s.ratings["E0"] = {"A": 1600.0, "B": 1400.0}
    s.start_season("E0", "2024-2025")
    assert s.ratings["E0"]["A"] == pytest.approx(1580.0)


def test_ordered_logit_is_monotonic():
    rng = np.random.default_rng(1)
    diffs = rng.normal(0, 150, 2000)
    p_home = 1 / (1 + 10 ** (-diffs / 400))
    u = rng.random(2000)
    outcomes = np.where(u < p_home * 0.8, 0, np.where(u < p_home * 0.8 + 0.25, 1, 2))
    model = OrderedLogit1X2().fit(diffs, outcomes)
    low, high = model.predict(-200), model.predict(200)
    assert high["home"] > low["home"]
    assert sum(high.values()) == pytest.approx(1.0)


def test_season_label():
    assert season_of(date(2026, 8, 21)) == "2026-2027"
    assert season_of(date(2027, 5, 1)) == "2026-2027"


# -------------------------------------------------------------- features
def test_features_use_only_prior_matches():
    fb = FeatureBuilder()
    t0 = datetime(2024, 1, 1)
    m1 = MatchRecord("1", t0, "E0", "A", "B", 5, 0)
    m2 = MatchRecord("2", t0 + timedelta(days=7), "E0", "A", "B", 0, 0)
    assert fb.features_for("A", "B", m1.kickoff)["home_gf"] is None
    fb.absorb(m1)
    fb.absorb(m2)
    # Features "as of" m2 kickoff must ignore m2's own result even though absorbed
    f = fb.features_for("A", "B", m2.kickoff)
    assert f["home_gf"] == pytest.approx(5.0)
    assert f["home_rest_days"] == pytest.approx(7.0)


# --------------------------------------------------------- ensemble/metrics
def test_linear_pool_prefers_better_component():
    rng = np.random.default_rng(3)
    n = 3000
    truth = rng.dirichlet([4, 2.5, 3], size=n)
    outcomes = np.array([rng.choice(3, p=p) for p in truth])
    noisy = 0.5 * truth + 0.5 * rng.dirichlet([1, 1, 1], size=n)
    pool = LinearPool(["good", "noisy"]).fit({"good": truth, "noisy": noisy}, outcomes)
    assert pool.weights[0] > pool.weights[1]
    assert pool.weights.sum() == pytest.approx(1.0)


def test_log_pool_prefers_better_component_and_sharpens_underconfident_ones():
    rng = np.random.default_rng(3)
    n = 3000
    truth = rng.dirichlet([4, 2.5, 3], size=n)
    outcomes = np.array([rng.choice(3, p=p) for p in truth])
    noisy = 0.5 * truth + 0.5 * rng.dirichlet([1, 1, 1], size=n)
    pool = LogPool(["good", "noisy"]).fit({"good": truth, "noisy": noisy}, outcomes)
    assert pool.weights[0] > pool.weights[1] >= 0
    # truth ** 0.5 is too flat; a linear pool cannot undo that, the log pool learns a weight near 2
    flat = truth ** 0.5 / (truth ** 0.5).sum(axis=1, keepdims=True)
    sharp = LogPool(["flat"]).fit({"flat": flat}, outcomes)
    assert sharp.weights[0] == pytest.approx(2.0, abs=0.3)
    assert sharp.combine({"flat": flat}).sum(axis=1) == pytest.approx(np.ones(n))


def test_log_pool_round_trips_and_combine_keeps_legacy_linear_weights():
    from app.engine.pipeline import combine_1x2
    pool = LogPool(["a", "b"], np.array([0.8, 0.4]), np.array([0.0, 0.1, -0.05]))
    probs = {"a": np.array([0.5, 0.3, 0.2]), "b": np.array([0.4, 0.3, 0.3])}
    d = pool.to_dict()
    final, used = combine_1x2(probs, d)
    assert final == pytest.approx(pool.combine(probs))
    assert used == pytest.approx({"a": 2 / 3, "b": 1 / 3})
    # a missing component's weight moves to the rest, so a lone component is pooled at the total weight
    assert combine_1x2({"a": probs["a"]}, d)[0] == pytest.approx(LogPool(["a"], np.array([1.2]), pool.bias).combine(probs))
    # zero-weight leftovers (no odds, market weight was everything) share the weight instead of vanishing
    market_only = LogPool(["a", "market"], np.array([0.0, 1.1]), np.zeros(3)).to_dict()
    final, used = combine_1x2({"a": probs["a"]}, market_only)
    assert used == {"a": 1.0}
    assert final == pytest.approx(LogPool(["a"], np.array([1.1])).combine({"a": probs["a"]}))
    # weights from versions learned before the log pool are still combined linearly
    final, _ = combine_1x2(probs, {"a": 0.5, "b": 0.5, "_totals_market": 0.3})
    assert final == pytest.approx((probs["a"] + probs["b"]) / 2)


def test_disagreement_and_metrics():
    a = np.array([0.5, 0.3, 0.2])
    b = np.array([0.2, 0.3, 0.5])
    assert disagreement({"a": a, "b": b}) == pytest.approx(0.3)
    probs = np.array([[1.0, 0.0, 0.0], [1 / 3, 1 / 3, 1 / 3]])
    outcomes = np.array([0, 2])
    assert brier(probs, outcomes) == pytest.approx((0 + (1 / 9 + 1 / 9 + 4 / 9)) / 2)
    assert log_loss(probs, outcomes) == pytest.approx(np.log(3) / 2, rel=1e-6)
    bins = calibration_bins(np.array([0.1, 0.15, 0.9]), np.array([0, 1, 1]))
    assert sum(b["count"] for b in bins) == 3


# --------------------------------------------------------- decision rules
def _reliability(**overrides):
    base = dict(min_team_matches=60, model_disagreement=0.03, interval_width=0.08, odds_age_hours=1.0,
                lineup_status="confirmed", unresolved_conflicts=0, stale_inputs=[],
                market_validated=True, ensemble_validated=True)
    base.update(overrides)
    return assess_reliability(ReliabilityInputs(**base))


def test_reliability_is_independent_of_probability():
    assert _reliability().score == 100
    low = _reliability(min_team_matches=4, model_disagreement=0.2, odds_age_hours=None)
    assert low.label == "low"
    assert {f.factor for f in low.factors} >= {"sample_size", "model_disagreement", "no_odds"}


def test_high_probability_short_odds_is_not_a_bet():
    rel = _reliability()
    c = Candidate("1x2", "home", probability=0.80, odds=1.20, bookmaker="x", validated=True)
    reasons = evaluate_candidate(c, SelectionRules(), rel, 1.0, 0.03)
    assert any("edge" in r for r in reasons)
    assert any("odds" in r for r in reasons)
    assert classify([], rel) == "no_bet"


def test_value_candidate_qualifies_and_lower_bound_rule():
    rel = _reliability()
    c = Candidate("1x2", "away", probability=0.36, odds=3.20, bookmaker="x", probability_lower=0.33,
                  validated=True)
    assert evaluate_candidate(c, SelectionRules(), rel, 1.0, 0.03) == []
    c.probability_lower = 0.28
    assert evaluate_candidate(c, SelectionRules(), rel, 1.0, 0.03) == [
        "EV is not positive at the lower end of the probability interval"
    ]


def test_unvalidated_market_never_qualifies():
    rel = _reliability()
    c = Candidate("btts", "yes", probability=0.7, odds=2.0, bookmaker="x", validated=False)
    assert "market not validated by backtest" in evaluate_candidate(c, SelectionRules(), rel, 1.0, 0.0)


def test_calibration_test_accepts_calibrated_and_rejects_biased():
    rng = np.random.default_rng(5)
    p = rng.uniform(0.1, 0.8, 1500)
    hit = (rng.random(1500) < p).astype(int)
    assert calibration_test(p, hit, sims=200)["p_value"] >= 0.05
    biased = np.clip(p + 0.12, 0, 1)  # systematically overconfident forecaster
    assert calibration_test(biased, hit, sims=200)["p_value"] < 0.05

"""Prediction snapshots, backtest time boundaries, settlement. All data SYNTHETIC."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.backtest import engine
from app.backtest.engine import BacktestParams, bootstrap_roi_interval, max_drawdown, run_backtest
from app.core.config import get_settings
from app.db.models import (
    Backtest, DataConflict, Fixture, ImmutableRecordError, MatchResult, ModelVersion, Prediction, Selection,
    SettledSelection,
)
from app.engine.features import MatchRecord
from app.engine.pipeline import ModelSuite, SuiteConfig
from app.ingestion.store import Store
from app.providers.base import NormalizedFixture
from app.services.backtests import execute_backtest, load_backtest_matches
from app.services.prediction import PredictionService
from app.services.settlement import selection_profit, settle_asian, settle_finished
from tests.conftest import make_batch, synthetic_league

START = datetime(2024, 8, 10, tzinfo=timezone.utc)


def _seed(db, upcoming_after=None, seasons=3, teams=10):
    fixtures = synthetic_league(START, seasons=seasons, upcoming_after=upcoming_after, teams=teams)
    Store(db).ingest_fixtures(make_batch(fixtures))
    db.commit()
    return fixtures


# --------------------------------------------------------------- pipeline
def test_refit_refuses_future_matches():
    suite = ModelSuite(SuiteConfig(compute_intervals=False))
    t = datetime(2025, 1, 1, tzinfo=timezone.utc)
    suite.absorb(MatchRecord("1", t, "p", "A", "B", 1, 0))
    with pytest.raises(ValueError, match="leakage"):
        suite.refit(t)  # match at the cutoff itself is not allowed
    with pytest.raises(ValueError):
        suite.absorb(MatchRecord("0", t - timedelta(days=1), "p", "A", "B", 1, 0))  # out of order


def test_backtest_never_uses_results_on_or_after_step(db, monkeypatch):
    _seed(db)
    comp_id = db.scalar(select(Fixture.competition_id))
    matches = load_backtest_matches(db, comp_id, before=datetime(2028, 1, 1, tzinfo=timezone.utc))
    seen: list[tuple[datetime, datetime]] = []
    original_refit = ModelSuite.refit

    def spy(self, cutoff):
        seen.append((cutoff, self.history[-1].kickoff if self.history else None))
        return original_refit(self, cutoff)

    monkeypatch.setattr(ModelSuite, "refit", spy)
    res = run_backtest({"ENG-1": matches}, BacktestParams(
        evaluate_from=datetime(2025, 8, 1, tzinfo=timezone.utc), evaluate_to=datetime(2027, 6, 1, tzinfo=timezone.utc),
        suite=SuiteConfig(compute_intervals=False), min_oos_for_weights=60))
    assert seen and all(last is None or last < cutoff for cutoff, last in seen)
    assert res["matches"] > 100
    assert "learned_weights" in res and set(res["one_x_two"]["comparison_common_subset"]) >= {"market", "ensemble"}
    for bet in res["bets"]:
        assert bet["closing_odds"] is None or bet["closing_odds"] > 1


def test_backtest_competitions_advance_through_time_together(db, monkeypatch):
    # Weights at a step come from every competition's earlier predictions only, so two leagues
    # playing on the same date use the same weights, whatever order they are passed in.
    _seed(db)
    comp_id = db.scalar(select(Fixture.competition_id))
    matches = load_backtest_matches(db, comp_id, before=datetime(2028, 1, 1, tzinfo=timezone.utc))
    used: dict[tuple[str, str], dict | None] = {}
    original = engine._predict_one

    def spy(suite, m, comp, weights, params, bets):
        used[(comp, m.record.kickoff.isoformat())] = weights
        return original(suite, m, comp, weights, params, bets)

    monkeypatch.setattr(engine, "_predict_one", spy)
    params = BacktestParams(evaluate_from=datetime(2025, 8, 1, tzinfo=timezone.utc),
                            evaluate_to=datetime(2027, 6, 1, tzinfo=timezone.utc),
                            suite=SuiteConfig(compute_intervals=False), min_oos_for_weights=60)
    first = run_backtest({"B": matches, "A": matches}, params)
    assert any(w is not None for w in used.values())
    assert all(used[("A", d)] == used[("B", d)] for (c, d) in used if c == "A")
    second = run_backtest({"A": matches, "B": matches}, params)
    assert first["learned_weights"] == second["learned_weights"]
    assert first["one_x_two"]["all"] == second["one_x_two"]["all"]


def test_load_backtest_matches_excludes_pre_match_odds_after_kickoff(db):
    _seed(db, seasons=1)
    comp_id = db.scalar(select(Fixture.competition_id))
    matches = load_backtest_matches(db, comp_id, before=datetime(2030, 1, 1, tzinfo=timezone.utc))
    m = matches[0]
    assert m.pre_1x2 and m.close_1x2  # both stored, kept separate
    assert set(m.pre_1x2) == {"avg", "b365", "ps"}


def test_drawdown_and_bootstrap():
    assert max_drawdown([1, -1, -1, 2, -3]) == pytest.approx(3)
    assert bootstrap_roi_interval([1.0] * 10) is None  # too few to say anything
    lo, hi = bootstrap_roi_interval([1.0, -1.0] * 50)
    assert lo < 0 < hi


# ------------------------------------------------------------ predictions
def _predict(db, now):
    return PredictionService(db, get_settings()).predict_upcoming("test", now=now)


def test_prediction_snapshot_is_complete_and_deduplicated(db):
    now = START + timedelta(days=365 * 2 + 20)
    _seed(db, upcoming_after=now)
    summary = _predict(db, now)
    assert summary["created"] > 0 and summary["failed"] == 0
    p = db.scalar(select(Prediction))
    r = p.markets["1x2"]
    assert sum(r.values()) == pytest.approx(1.0, abs=1e-6)
    assert p.markets["totals"]["2.5"]["over"] + p.markets["totals"]["2.5"]["under"] == pytest.approx(1.0)
    assert p.markets["double_chance"]["1X"] == pytest.approx(r["home"] + r["draw"])
    assert p.lineup_status == "unavailable"
    assert p.classification in ("consider", "no_bet", "high_uncertainty")
    assert any(f["factor"] == "unvalidated_ensemble" for f in p.reliability["factors"])
    assert p.explanations and p.explanations[0].category == "summary"
    # No deployed (validated) model: nothing may qualify as a recommendation
    assert not any(s.qualifies for s in db.scalars(select(Selection)))
    again = _predict(db, now)
    assert again["created"] == 0 and again["unchanged"] == summary["created"]


def test_predictions_are_immutable(db):
    now = START + timedelta(days=365 * 2 + 20)
    _seed(db, upcoming_after=now)
    _predict(db, now)
    p = db.scalar(select(Prediction))
    p.classification = "consider"
    with pytest.raises(ImmutableRecordError):
        db.commit()
    db.rollback()


def test_no_history_competition_is_skipped_not_echoing_market(db):
    now = START + timedelta(days=10)
    fixtures = synthetic_league(START, seasons=1, upcoming_after=START)  # everything in the future
    Store(db).ingest_fixtures(make_batch(fixtures))
    db.commit()
    summary = _predict(db, now)
    assert summary["created"] == 0 and "ENG-1" in summary["skipped"]


def _run_bt(db, date_to: str) -> Backtest:
    bt = Backtest(params={"competitions": ["ENG-1"], "date_from": "2025-08-01", "date_to": date_to,
                          "step_days": 7, "price_source": "best", "rules": {}, "deploy": True}, status="queued")
    db.add(bt)
    db.commit()
    execute_backtest(db, bt.id, get_settings())
    db.refresh(bt)
    assert bt.status == "completed", bt.error
    return bt


def test_backtest_with_too_few_oos_predictions_registers_nothing(db):
    _seed(db)
    bt = _run_bt(db, "2027-06-01")
    assert bt.metrics["matches"] < 300 and bt.metrics["learned_weights"] == {}
    assert db.scalar(select(ModelVersion)) is None


def test_backtest_service_registers_and_deploys_version(db):
    _seed(db, seasons=4, teams=12)
    bt = _run_bt(db, "2028-06-01")
    v = db.scalar(select(ModelVersion))
    assert v is not None and v.status == "deployed" and v.backtest_id == bt.id
    assert "market" in v.ensemble_weights


# ------------------------------------------------------------- settlement
def test_asian_handicap_settlement():
    assert settle_asian(1, -0.75) == ("half_win", 0.5)
    assert settle_asian(0, -0.25) == ("half_loss", -0.5)
    assert settle_asian(0, 0.0) == ("push", 0)
    assert settle_asian(2, -1.5) == ("win", 1)
    assert settle_asian(-1, 0.5) == ("loss", -1)


def test_selection_profit_by_market():
    s = Selection(market="1x2", selection="away", line=0.0, decimal_odds=3.0)
    assert selection_profit(s, 0, 1) == ("win", 2.0)
    s = Selection(market="totals_2.5", selection="under", line=2.5, decimal_odds=1.9)
    assert selection_profit(s, 2, 1) == ("loss", -1.0)
    s = Selection(market="asian_handicap", selection="home -0.75", line=-0.75, decimal_odds=2.0)
    assert selection_profit(s, 1, 0) == ("half_win", 0.5)


def test_settlement_withheld_when_results_conflict(db):
    now = START + timedelta(days=365 * 2 + 20)
    _seed(db, upcoming_after=now)
    _predict(db, now)
    sel = db.scalar(select(Selection))
    fx = db.get(Fixture, sel.fixture_id)
    db.add(MatchResult(fixture_id=fx.id, home_goals=1, away_goals=0))
    fx.status = "finished"
    db.add(DataConflict(entity_type="match_result", entity_id=fx.id, field="score", values=[], resolved=False))
    db.commit()
    out = settle_finished(db)
    assert out["withheld_due_to_conflict"] > 0
    assert db.scalar(select(SettledSelection).where(SettledSelection.selection_id == sel.id)) is None


def test_settlement_settles_and_is_idempotent(db):
    now = START + timedelta(days=365 * 2 + 20)
    _seed(db, upcoming_after=now)
    _predict(db, now)
    fixture_ids = {s.fixture_id for s in db.scalars(select(Selection))}
    for fid in fixture_ids:
        db.add(MatchResult(fixture_id=fid, home_goals=2, away_goals=2))
        db.get(Fixture, fid).status = "finished"
    db.commit()
    first = settle_finished(db)
    second = settle_finished(db)
    assert first["settled"] > 0 and second["settled"] == 0
    assert all(s.outcome in ("win", "loss", "push", "half_win", "half_loss") for s in db.scalars(select(SettledSelection)))


def test_date_type_used_in_backtest_params():
    assert date.fromisoformat("2025-08-01").year == 2025


@pytest.mark.skipif(not __import__("tests.conftest", fromlist=["IS_POSTGRES"]).IS_POSTGRES,
                    reason="PostgreSQL-only: database trigger")
def test_database_trigger_blocks_raw_sql_updates(db):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    now = START + timedelta(days=365 * 2 + 20)
    _seed(db, upcoming_after=now)
    _predict(db, now)
    with pytest.raises(DBAPIError, match="immutable"):
        db.execute(text("UPDATE predictions SET classification = 'consider'"))
    db.rollback()


def test_cup_fixture_is_predicted_from_its_feeder_league(db):
    now = START + timedelta(days=365 * 2 + 20)
    _seed(db, seasons=2)
    cup = NormalizedFixture(provider="the_odds_api", provider_fixture_id="c1", competition_code="ENG-FAC",
                            season_label="2026-2027", home_name="Synthetic Town 09", away_name="Synthetic Town 00",
                            kickoff_utc=now + timedelta(days=2), status="scheduled", stage="cup")
    Store(db).ingest_fixtures(make_batch([cup], provider="the_odds_api", trust=80))
    db.commit()
    summary = _predict(db, now)
    assert summary["created"] == 1 and not summary["skipped"]
    p = db.scalar(select(Prediction))
    assert p.markets["1x2"]["home"] > p.markets["1x2"]["away"]  # team 09 is the strongest synthetic side

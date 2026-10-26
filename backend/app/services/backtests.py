"""Run walk-forward backtests from stored data and register model versions."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest.engine import BacktestMatch, BacktestParams, run_backtest
from app.core.config import Settings
from app.db.models import Backtest, Bookmaker, Competition, Fixture, ModelVersion, OddsSnapshot
from app.engine.decision import SelectionRules
from app.engine.features import MODEL_FEATURES
from app.services.analytics import load_records
from app.services.prediction import suite_config

log = logging.getLogger(__name__)

MODEL_NAME = "ensemble-dc-elo-logit-market"


def load_backtest_matches(db: Session, competition_id: int, before: datetime) -> list[BacktestMatch]:
    records = load_records(db, competition_id, before=before)
    by_id = {int(r.key): BacktestMatch(record=r, competition=str(competition_id)) for r in records}
    if not by_id:
        return []
    q = (
        select(OddsSnapshot.fixture_id, Bookmaker.key, OddsSnapshot.market, OddsSnapshot.line,
               OddsSnapshot.selection, OddsSnapshot.decimal_odds, OddsSnapshot.kind, OddsSnapshot.observed_at)
        .join(Bookmaker, Bookmaker.id == OddsSnapshot.bookmaker_id)
        .join(Fixture, Fixture.id == OddsSnapshot.fixture_id)
        .where(Fixture.competition_id == competition_id, Fixture.kickoff_utc < before,
               OddsSnapshot.market.in_(("1x2", "totals")))
        .order_by(OddsSnapshot.observed_at)
    )
    for fid, bk, market, line, sel, price, kind, observed in db.execute(q):
        m = by_id.get(fid)
        if m is None:
            continue
        if kind == "pre_match" and observed >= m.record.kickoff:
            continue  # leakage guard: only prices observed before kickoff count as pre-match
        if market == "totals" and abs(line - 2.5) > 1e-9:
            continue
        target = {("1x2", "pre_match"): m.pre_1x2, ("1x2", "closing"): m.close_1x2,
                  ("totals", "pre_match"): m.pre_totals, ("totals", "closing"): m.close_totals}[(market, kind)]
        target.setdefault(bk, {})[sel] = price  # ordered by time: latest snapshot wins
    return list(by_id.values())


def execute_backtest(db: Session, backtest_id: int, settings: Settings) -> Backtest:
    bt = db.get(Backtest, backtest_id)
    bt.status = "running"
    db.commit()
    try:
        p = bt.params
        date_from = datetime.fromisoformat(p["date_from"]).replace(tzinfo=timezone.utc)
        date_to = datetime.fromisoformat(p["date_to"]).replace(tzinfo=timezone.utc)
        comps = list(db.scalars(select(Competition).where(Competition.code.in_(p["competitions"]))))
        data = {c.code: load_backtest_matches(db, c.id, before=date_to) for c in comps}
        suite = suite_config(settings)
        suite.compute_intervals = False
        rules = SelectionRules(**{**SelectionRules().__dict__, **p.get("rules", {})})
        rules.require_lower_bound_ev_positive = False  # intervals are not computed in backtests (speed)
        params = BacktestParams(evaluate_from=date_from, evaluate_to=date_to, step_days=p.get("step_days", 7),
                                price_source=p.get("price_source", "best"), rules=rules, suite=suite)
        metrics = run_backtest(data, params)
        metrics["notes"] = [
            "Walk-forward: models refit at each step using only matches before the step start.",
            "Ensemble weights at each step were learned from earlier out-of-sample predictions only.",
            "Pre-match odds are football-data.co.uk snapshots taken before kickoff; closing odds are used only for CLV.",
            "Lower-bound EV rule disabled in backtests (no parameter intervals computed for speed).",
            "Lineups/injuries are not part of historical data: every backtest prediction is pre-lineup.",
        ]
        bt.metrics = metrics
        bt.status = "completed"
        bt.finished_at = datetime.now(timezone.utc)
        db.commit()
        if metrics.get("learned_weights"):
            register_version(db, bt, deploy=p.get("deploy", False))
    except Exception as exc:  # noqa: BLE001
        log.exception("backtest %s failed", backtest_id)
        db.rollback()
        bt = db.get(Backtest, backtest_id)
        bt.status, bt.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
        bt.finished_at = datetime.now(timezone.utc)
        db.commit()
    return bt


def register_version(db: Session, bt: Backtest, deploy: bool) -> ModelVersion:
    m = bt.metrics
    version = ModelVersion(
        name=MODEL_NAME, version=f"{datetime.now(timezone.utc):%Y%m%d%H%M%S}-bt{bt.id}",
        status="candidate", trained_from=datetime.fromisoformat(m["date_from"]).date(),
        trained_to=datetime.fromisoformat(m["date_to"]).date(), config={"backtest_params": bt.params},
        feature_definitions=[
            {"name": "elo_diff", "definition": "Elo(home) + home advantage - Elo(away), /100"},
            {"name": "gf_diff", "definition": "recency-weighted goals for, last 10, home minus away"},
            {"name": "ga_diff", "definition": "recency-weighted goals against, last 10, home minus away"},
            {"name": "sot_diff", "definition": "net shots on target (for - against), home minus away"},
            {"name": "ppg_diff", "definition": "recency-weighted points per game, home minus away"},
            {"name": "rest_diff", "definition": "days since previous match (capped at 14), home minus away"},
        ] if MODEL_FEATURES else [],
        ensemble_weights=m["learned_weights"], validated_markets=m.get("validated_markets", []),
        metrics={"one_x_two": m["one_x_two"]["all"], "calibration_ece": m.get("calibration_ece"),
                 "betting": m["betting"]["overall"], "totals_2.5": (m.get("totals_2.5") or {}).get("model")},
        backtest_id=bt.id,
    )
    db.add(version)
    db.flush()
    if deploy:
        deploy_version(db, version)
    db.commit()
    return version


def deploy_version(db: Session, version: ModelVersion) -> None:
    for v in db.scalars(select(ModelVersion).where(ModelVersion.status == "deployed")):
        if v.id != version.id:
            v.status = "retired"
    version.status = "deployed"

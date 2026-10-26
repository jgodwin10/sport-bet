from __future__ import annotations

from collections import defaultdict

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.predictions import latest_prediction_ids
from app.backtest.engine import bootstrap_roi_interval, max_drawdown
from app.db.models import Backtest, Fixture, MatchResult, ModelVersion, Prediction, Selection, SettledSelection
from app.db.session import get_db
from app.engine.ensemble import brier, calibration_bins, log_loss
from app.schemas.api import ModelVersionOut

router = APIRouter(tags=["performance"])


def _bet_stats(rows: list[tuple[float, float | None, str]]) -> dict:
    profits = [p for p, _, _ in rows]
    clvs = [c for _, c, _ in rows if c is not None]
    if not profits:
        return {"selections": 0, "profit": 0.0, "roi": None, "max_drawdown": 0.0, "roi_interval_90": None,
                "clv_mean": None, "sample_warning": "no settled selections yet"}
    return {
        "selections": len(profits), "profit": round(sum(profits), 3), "roi": sum(profits) / len(profits),
        "hit_rate": sum(p > 0 for p in profits) / len(profits), "max_drawdown": max_drawdown(profits),
        "roi_interval_90": bootstrap_roi_interval(profits), "clv_mean": float(np.mean(clvs)) if clvs else None,
        "sample_warning": "fewer than 200 selections: results are dominated by noise" if len(profits) < 200 else None,
    }


def _prospective(db: Session) -> dict:
    """Live (prospective) results: final pre-kickoff snapshot per fixture only."""
    latest = latest_prediction_ids()
    q = (select(Selection.market, SettledSelection.profit, SettledSelection.clv, SettledSelection.outcome)
         .join(SettledSelection, SettledSelection.selection_id == Selection.id)
         .where(Selection.prediction_id.in_(latest), Selection.qualifies.is_(True)))
    by_market = defaultdict(list)
    all_rows = []
    for market, profit, clv, outcome in db.execute(q):
        by_market[market].append((profit, clv, outcome))
        all_rows.append((profit, clv, outcome))

    # Probability quality of the final pre-match 1X2 on finished fixtures
    preds = db.execute(select(Prediction.markets, Prediction.lineup_status, MatchResult.home_goals,
                              MatchResult.away_goals)
                       .join(Fixture, Fixture.id == Prediction.fixture_id)
                       .join(MatchResult, MatchResult.fixture_id == Fixture.id)
                       .where(Prediction.id.in_(latest)))
    probs, outcomes, lineup = [], [], []
    for markets, lineup_status, hg, ag in preds:
        r = markets.get("1x2")
        if not r:
            continue
        probs.append([r["home"], r["draw"], r["away"]])
        outcomes.append(0 if hg > ag else 1 if hg == ag else 2)
        lineup.append(lineup_status)
    quality = None
    if probs:
        p, o = np.array(probs), np.array(outcomes)
        quality = {"n": len(o), "log_loss": log_loss(p, o), "brier": brier(p, o),
                   "accuracy": float((p.argmax(1) == o).mean()),
                   "calibration_home": calibration_bins(p[:, 0], (o == 0).astype(int), bins=5)}
        by_lineup = {}
        for status in set(lineup):
            idx = [i for i, s in enumerate(lineup) if s == status]
            by_lineup[status] = {"n": len(idx), "log_loss": log_loss(p[idx], o[idx])}
        quality["by_lineup_status"] = by_lineup
    return {"overall": _bet_stats(all_rows), "by_market": {m: _bet_stats(r) for m, r in by_market.items()},
            "probability_quality": quality}


@router.get("/performance/summary")
def performance_summary(db: Session = Depends(get_db)) -> dict:
    deployed = db.scalar(select(ModelVersion).where(ModelVersion.status == "deployed")
                         .order_by(ModelVersion.created_at.desc()).limit(1))
    bt = db.get(Backtest, deployed.backtest_id) if deployed and deployed.backtest_id else db.scalar(
        select(Backtest).where(Backtest.status == "completed").order_by(Backtest.created_at.desc()).limit(1))
    backtest = None
    if bt and bt.metrics:
        m = bt.metrics
        backtest = {k: m.get(k) for k in ("matches", "date_from", "date_to", "calibration_ece", "validated_markets",
                                          "learned_weights", "price_source", "notes")}
        backtest["id"] = bt.id
        backtest["one_x_two"] = m.get("one_x_two")
        backtest["betting_overall"] = m.get("betting", {}).get("overall")
    return {
        "deployed_model": ModelVersionOut.model_validate(deployed).model_dump() if deployed else None,
        "prospective": _prospective(db), "latest_backtest": backtest,
        "disclosure": "Historical performance includes every losing selection. Positive past returns, especially "
                      "on small samples, are not evidence of a reliable edge.",
    }


@router.get("/performance/markets")
def performance_markets(db: Session = Depends(get_db)) -> dict:
    bt = db.scalar(select(Backtest).where(Backtest.status == "completed").order_by(Backtest.created_at.desc()).limit(1))
    m = bt.metrics if bt else {}
    return {
        "prospective": _prospective(db)["by_market"],
        "backtest": {"backtest_id": bt.id if bt else None,
                     "betting_by_market": m.get("betting", {}).get("by_market"),
                     "betting_by_odds_range": m.get("betting", {}).get("by_odds_range"),
                     "betting_by_competition": m.get("betting", {}).get("by_competition"),
                     "totals_2.5": m.get("totals_2.5"), "calibration": m.get("calibration")},
    }


@router.get("/models", response_model=list[ModelVersionOut])
def list_models(db: Session = Depends(get_db)) -> list[ModelVersion]:
    return list(db.scalars(select(ModelVersion).order_by(ModelVersion.created_at.desc())))


@router.get("/models/{model_id}", response_model=ModelVersionOut)
def get_model(model_id: int, db: Session = Depends(get_db)) -> ModelVersion:
    m = db.get(ModelVersion, model_id)
    if m is None:
        raise HTTPException(404, "model version not found")
    return m

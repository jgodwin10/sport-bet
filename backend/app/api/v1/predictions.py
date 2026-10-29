from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.api.v1.serializers import prediction_detail, team_ref
from app.db.models import Competition, Fixture, Prediction, Selection, SettledSelection, Team
from app.db.session import get_db
from app.providers.ai import get_ai
from app.schemas.api import Page, SelectionRow, TopPickRecord, TopPickResult, TopPickRow, TopPicks
from app.services.top_picks import latest_prediction_ids, top_picks, track_record

router = APIRouter(prefix="/predictions", tags=["predictions"])

SORTS = {"expected_value": Selection.expected_value, "edge": Selection.edge, "probability": Selection.probability,
         "kickoff": Fixture.kickoff_utc, "odds": Selection.decimal_odds, "predicted_at": Prediction.created_at}


def selection_row(s: Selection, p: Prediction, f: Fixture, comp: str, home: Team, away: Team,
                  st: SettledSelection | None, now: datetime) -> dict:
    state = "settled" if st else ("upcoming" if f.kickoff_utc > now else "awaiting_result")
    return dict(
        selection_id=s.id, prediction_id=p.id, fixture_id=f.id, match=f"{home.name} v {away.name}",
        home_team=team_ref(home), away_team=team_ref(away), competition=comp,
        kickoff_utc=f.kickoff_utc, market=s.market, selection=s.selection, probability=s.probability,
        probability_lower=s.probability_lower, odds=s.decimal_odds, bookmaker=s.bookmaker,
        implied_probability=s.implied_probability, fair_probability=s.fair_probability, edge=s.edge,
        expected_value=s.expected_value, qualifies=s.qualifies, rejection_reasons=s.rejection_reasons,
        reliability_score=p.reliability["score"], reliability_label=p.reliability["label"],
        odds_age_hours=p.data_quality.get("odds_age_hours"), predicted_at=p.created_at, status=state,
        outcome=st.outcome if st else None, profit=st.profit if st else None, clv=st.clv if st else None,
    )


@router.get("", response_model=Page[SelectionRow])
def list_predictions(
    db: Session = Depends(get_db),
    status: str = Query("upcoming", pattern="^(upcoming|settled|all)$"),
    qualifying_only: bool = False,
    market: str | None = Query(default=None, max_length=30),
    competition: list[str] | None = Query(default=None),
    search: str | None = Query(default=None, max_length=80),
    min_probability: float | None = Query(default=None, ge=0, le=1),
    min_edge: float | None = Query(default=None, ge=-1, le=1),
    min_ev: float | None = Query(default=None, ge=-1, le=10),
    min_odds: float | None = Query(default=None, ge=1),
    max_odds: float | None = Query(default=None, ge=1),
    sort: str = Query("expected_value", pattern="^(expected_value|edge|probability|kickoff|odds|predicted_at)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
) -> Page[SelectionRow]:
    now = datetime.now(timezone.utc)
    ht, at = aliased(Team), aliased(Team)
    q = (
        select(Selection, Prediction, Fixture, Competition.code, ht, at, SettledSelection)
        .join(Prediction, Prediction.id == Selection.prediction_id)
        .join(Fixture, Fixture.id == Selection.fixture_id)
        .join(Competition, Competition.id == Fixture.competition_id)
        .join(ht, ht.id == Fixture.home_team_id).join(at, at.id == Fixture.away_team_id)
        .outerjoin(SettledSelection, SettledSelection.selection_id == Selection.id)
        .where(Prediction.id.in_(latest_prediction_ids()))
    )
    if status == "upcoming":
        q = q.where(Fixture.kickoff_utc > now, Fixture.status == "scheduled")
    elif status == "settled":
        q = q.where(SettledSelection.selection_id.is_not(None))
    if qualifying_only:
        q = q.where(Selection.qualifies.is_(True))
    if market:
        q = q.where(Selection.market == market)
    if competition:
        q = q.where(Competition.code.in_(competition))
    if search:
        q = q.where(ht.name.ilike(f"%{search}%") | at.name.ilike(f"%{search}%"))
    for col, val, op in ((Selection.probability, min_probability, "ge"), (Selection.edge, min_edge, "ge"),
                         (Selection.expected_value, min_ev, "ge"), (Selection.decimal_odds, min_odds, "ge"),
                         (Selection.decimal_odds, max_odds, "le")):
        if val is not None:
            q = q.where(col >= val if op == "ge" else col <= val)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    col = SORTS[sort]
    q = q.order_by(col.desc() if order == "desc" else col.asc(), Selection.id).offset((page - 1) * page_size).limit(page_size)
    items = [SelectionRow(**selection_row(s, p, f, comp, home, away, st, now))
             for s, p, f, comp, home, away, st in db.execute(q)]
    return Page(items=items, total=total or 0, page=page, page_size=page_size)


@router.get("/top", response_model=TopPicks)
def list_top_picks(db: Session = Depends(get_db), limit: int = Query(10, ge=1, le=25),
                   days: int = Query(7, ge=1, le=14)) -> TopPicks:
    now = datetime.now(timezone.utc)
    picks = top_picks(db, now, limit=limit, days=days)
    return TopPicks(
        generated_at=now, days=days, ai_configured=get_ai().configured,
        items=[TopPickRow(**selection_row(t.selection, t.prediction, t.fixture, t.competition, t.home, t.away,
                                          None, now), rank=i, tier=t.tier, score=t.score, ai=t.ai)
               for i, t in enumerate(picks, 1)],
    )


@router.get("/top/record", response_model=TopPickRecord)
def top_picks_record(db: Session = Depends(get_db), limit: int = Query(100, ge=1, le=500)) -> TopPickRecord:
    rec = track_record(db, datetime.now(timezone.utc), limit=limit)
    history = []
    for h in rec["history"]:
        e, s, f, st = h["entry"], h["selection"], h["fixture"], h["settled"]
        history.append(TopPickResult(
            fixture_id=f.id, match=f"{h['home'].name} v {h['away'].name}", home_team=team_ref(h["home"]),
            away_team=team_ref(h["away"]), competition=h["competition"], kickoff_utc=f.kickoff_utc,
            market=s.market, selection=s.selection, odds=s.decimal_odds, probability=s.probability,
            expected_value=s.expected_value, rank=e.rank, best_rank=e.best_rank, tier=e.tier, counted=h["counted"],
            score={"home": f.result.home_goals, "away": f.result.away_goals} if f.result else None,
            outcome=st.outcome if st else None, profit=st.profit if st else None, clv=st.clv if st else None,
            running_profit=h["running_profit"],
        ))
    return TopPickRecord(summary=rec["summary"], dropped=rec["dropped"], history=history)


@router.get("/{prediction_id}")
def get_prediction(prediction_id: int, db: Session = Depends(get_db)) -> dict:
    p = db.get(Prediction, prediction_id)
    if p is None:
        raise HTTPException(404, "prediction not found")
    return prediction_detail(p)

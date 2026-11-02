from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.api.v1.serializers import prediction_detail, team_ref
from app.core.config import get_settings
from app.db.models import Competition, DailySlip, Fixture, Prediction, Selection, SettledSelection, Team
from app.db.session import get_db
from app.providers.ai import get_ai
from app.schemas.api import (
    Page, SelectionRow, TopPickRecord, TopPickResult, TopPickRow, TopPicks, TwoOddsLeg, TwoOddsRecord, TwoOddsResult,
    TwoOddsSlip,
)
from app.services import two_odds
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


def day_window(day: str, tz: str, now: datetime) -> tuple[datetime, datetime]:
    """UTC bounds of the viewer's local calendar day (today or tomorrow) in `tz`."""
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, f"unknown time zone: {tz}") from None
    d = now.astimezone(zone).date() + timedelta(days=1 if day == "tomorrow" else 0)
    start = datetime(d.year, d.month, d.day, tzinfo=zone)
    nxt = d + timedelta(days=1)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=zone)  # not start + 24h: DST days are 23/25h
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


@router.get("/top", response_model=TopPicks)
def list_top_picks(db: Session = Depends(get_db), limit: int = Query(10, ge=1, le=25),
                   days: int = Query(7, ge=1, le=14),
                   day: str | None = Query(default=None, pattern="^(today|tomorrow)$"),
                   tz: str = Query("UTC", max_length=64)) -> TopPicks:
    now = datetime.now(timezone.utc)
    start, end = day_window(day, tz, now) if day else (now, now + timedelta(days=days))
    picks = top_picks(db, now, limit=limit, start=start, end=end)
    return TopPicks(
        generated_at=now, days=days, day=day, window_start=max(start, now), window_end=end,
        ai_configured=get_ai().configured,
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


def two_odds_leg(leg: dict, now: datetime) -> TwoOddsLeg:
    f = leg["fixture"]
    return TwoOddsLeg(
        **selection_row(leg["selection"], leg["prediction"], f, leg["competition"], leg["home"], leg["away"],
                        leg["settled"], now),
        checks=leg["checks"],
        score={"home": f.result.home_goals, "away": f.result.away_goals} if f.result else None,
    )


@router.get("/two-odds", response_model=TwoOddsSlip)
def daily_two_odds(db: Session = Depends(get_db), on: date | None = Query(default=None, alias="date")) -> TwoOddsSlip:
    now = datetime.now(timezone.utc)
    day = on or two_odds.slip_day(now, get_settings().two_odds_timezone)
    slip = db.get(DailySlip, day)
    legs = two_odds.load_legs(db, slip) if slip else []
    outcomes = [leg["outcome"] for leg in legs]
    status = two_odds.slip_status(outcomes)
    rules = two_odds.RULES
    return TwoOddsSlip(
        date=day, status=status, built=slip is not None,
        locked=any(leg["fixture"].kickoff_utc <= now for leg in legs),
        legs=[two_odds_leg(leg, now) for leg in legs],
        combined_odds=slip.combined_odds if slip else None,
        combined_probability=slip.combined_probability if slip else None,
        paid_odds=two_odds.settled_odds([(leg["selection"].decimal_odds, leg["outcome"]) for leg in legs])
        if status in ("won", "void") else None,
        analysed=slip.analysed if slip else 0, spare=slip.spare if slip else 0,
        rejected=slip.rejected if slip else [], changes=slip.changes if slip else [],
        updated_at=slip.updated_at if slip else None, ai_configured=get_ai().configured,
        min_combined_odds=rules.min_combined_odds, max_combined_odds=rules.max_combined_odds,
        min_leg_probability=rules.min_leg_probability,
    )


@router.get("/two-odds/record", response_model=TwoOddsRecord)
def two_odds_record(db: Session = Depends(get_db), limit: int = Query(60, ge=1, le=365)) -> TwoOddsRecord:
    rec = two_odds.track_record(db, limit=limit)
    now = datetime.now(timezone.utc)
    return TwoOddsRecord(summary=rec["summary"], backtest=rec["backtest"], history=[
        TwoOddsResult(date=h["slip"].slip_date, status=h["status"], combined_odds=h["slip"].combined_odds,
                      combined_probability=h["slip"].combined_probability, profit=h["profit"],
                      running_profit=round(h["running_profit"], 4), legs=[two_odds_leg(leg, now) for leg in h["legs"]])
        for h in rec["history"]])


@router.get("/{prediction_id}")
def get_prediction(prediction_id: int, db: Session = Depends(get_db)) -> dict:
    p = db.get(Prediction, prediction_id)
    if p is None:
        raise HTTPException(404, "prediction not found")
    return prediction_detail(p)

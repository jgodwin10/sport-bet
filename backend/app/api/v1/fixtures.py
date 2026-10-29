from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from app.api.v1.serializers import fixture_out, latest_predictions, prediction_detail
from app.api.v1.system import audit
from app.core.config import get_settings
from app.core.security import require_user
from app.db.models import (
    AvailabilityReport, Competition, Fixture, Lineup, Prediction, SourceRecord, Team, User,
)
from app.db.session import get_db
from app.providers.ai import AiUnavailable
from app.services.ai_analysis import AiAnalysisService, analysis_out
from app.schemas.api import FixtureAnalysis, FixtureOut, Page
from app.services.analytics import head_to_head, odds_at, standings, summarise_form, team_recent

router = APIRouter(prefix="/fixtures", tags=["fixtures"])

DISCLAIMER = ("Statistical estimates, not guarantees. Probabilities carry model and data uncertainty; "
              "expected value is an estimate that can be wrong. Never stake more than you can afford to lose.")


def _get_fixture(db: Session, fixture_id: int) -> Fixture:
    f = db.get(Fixture, fixture_id)
    if f is None:
        raise HTTPException(404, "fixture not found")
    return f


@router.get("", response_model=Page[FixtureOut])
def list_fixtures(
    db: Session = Depends(get_db),
    date_from: date | None = None, date_to: date | None = None,
    competition: list[str] | None = Query(default=None), country: str | None = None,
    team: str | None = Query(default=None, max_length=80),
    status: str | None = Query(default=None, pattern="^(scheduled|live|finished|postponed|abandoned|cancelled)$"),
    classification: str | None = Query(default=None, pattern="^(consider|no_bet|high_uncertainty)$"),
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
) -> Page[FixtureOut]:
    now = datetime.now(timezone.utc)
    start = datetime.combine(date_from, time.min, tzinfo=timezone.utc) if date_from else now - timedelta(hours=6)
    end = datetime.combine(date_to, time.max, tzinfo=timezone.utc) if date_to else now + timedelta(days=14)
    q = select(Fixture).join(Competition).where(Fixture.kickoff_utc.between(start, end))
    if competition:
        q = q.where(Competition.code.in_(competition))
    if country:
        q = q.where(Competition.country == country)
    if status:
        q = q.where(Fixture.status == status)
    if team:
        ht, at = aliased(Team), aliased(Team)
        q = q.join(ht, ht.id == Fixture.home_team_id).join(at, at.id == Fixture.away_team_id).where(
            or_(ht.name.ilike(f"%{team}%"), at.name.ilike(f"%{team}%")))
    fixtures = list(db.scalars(q.order_by(Fixture.kickoff_utc, Fixture.id)))
    preds = latest_predictions(db, [f.id for f in fixtures])
    if classification:
        fixtures = [f for f in fixtures if f.id in preds and preds[f.id].classification == classification]
    total = len(fixtures)
    window = fixtures[(page - 1) * page_size: page * page_size]
    return Page(items=[fixture_out(f, preds.get(f.id)) for f in window], total=total, page=page,
                page_size=page_size)


@router.get("/{fixture_id}", response_model=FixtureOut)
def get_fixture(fixture_id: int, db: Session = Depends(get_db)) -> FixtureOut:
    f = _get_fixture(db, fixture_id)
    return fixture_out(f, latest_predictions(db, [f.id]).get(f.id))


@router.get("/{fixture_id}/predictions")
def fixture_predictions(fixture_id: int, db: Session = Depends(get_db)) -> list[dict]:
    _get_fixture(db, fixture_id)
    preds = db.scalars(select(Prediction).where(Prediction.fixture_id == fixture_id)
                       .order_by(Prediction.created_at.desc(), Prediction.id.desc()))
    return [prediction_detail(p) for p in preds]


@router.get("/{fixture_id}/lineups")
def fixture_lineups(fixture_id: int, db: Session = Depends(get_db)) -> list[dict]:
    _get_fixture(db, fixture_id)
    return _lineups(db, fixture_id)


def _lineups(db: Session, fixture_id: int) -> list[dict]:
    rows = db.execute(select(Lineup, Team.name, SourceRecord.provider).join(Team, Team.id == Lineup.team_id)
                      .join(SourceRecord, SourceRecord.id == Lineup.source_record_id)
                      .where(Lineup.fixture_id == fixture_id).order_by(Lineup.retrieved_at.desc()))
    latest: dict[int, dict] = {}
    for lu, team, provider in rows:
        latest.setdefault(lu.team_id, {"team_id": lu.team_id, "team": team, "status": lu.status,
                                       "formation": lu.formation, "players": lu.players, "source": provider,
                                       "retrieved_at": lu.retrieved_at})
    return list(latest.values())


@router.get("/{fixture_id}/odds")
def fixture_odds(fixture_id: int, db: Session = Depends(get_db)) -> dict:
    f = _get_fixture(db, fixture_id)
    return _odds_payload(db, f)


def _odds_payload(db: Session, f: Fixture) -> dict:
    cutoff = min(datetime.now(timezone.utc), f.kickoff_utc)
    view = odds_at(db, f.id, cutoff)
    closing = odds_at(db, f.id, f.kickoff_utc, kind="closing") if f.status == "finished" else None
    rows = sorted(view.rows, key=lambda r: (r["market"], r["line"], r["bookmaker"], r["selection"]))
    return {
        "latest": [{**r, "observed_at": r["observed_at"].isoformat()} for r in rows],
        "latest_observed": view.latest_observed.isoformat() if view.latest_observed else None,
        "age_hours": ((datetime.now(timezone.utc) - view.latest_observed).total_seconds() / 3600)
        if view.latest_observed else None,
        "closing": [{**r, "observed_at": r["observed_at"].isoformat()} for r in closing.rows] if closing else [],
    }


@router.get("/{fixture_id}/analysis", response_model=FixtureAnalysis)
def fixture_analysis(fixture_id: int, db: Session = Depends(get_db)) -> FixtureAnalysis:
    f = _get_fixture(db, fixture_id)
    preds = list(db.scalars(select(Prediction).where(Prediction.fixture_id == f.id)
                            .order_by(Prediction.created_at.desc(), Prediction.id.desc())))
    latest = preds[0] if preds else None
    cutoff = min(datetime.now(timezone.utc), f.kickoff_utc)
    home_recent = team_recent(db, f.home_team_id, cutoff)
    away_recent = team_recent(db, f.away_team_id, cutoff)
    table = standings(db, f.season_id, cutoff)
    ctx = {r["team_id"]: r for r in table}
    avail = db.execute(select(AvailabilityReport, Team.name, SourceRecord.provider)
                       .join(Team, Team.id == AvailabilityReport.team_id)
                       .join(SourceRecord, SourceRecord.id == AvailabilityReport.source_record_id)
                       .where(AvailabilityReport.fixture_id == f.id)
                       .order_by(AvailabilityReport.retrieved_at.desc()))
    seen, availability = set(), []
    for a, team, provider in avail:
        if (a.team_id, a.player_name) in seen:
            continue
        seen.add((a.team_id, a.player_name))
        availability.append({"team": team, "team_id": a.team_id, "player": a.player_name, "kind": a.kind,
                             "reason": a.reason, "verification": a.verification,
                             "expected_return": a.expected_return, "source": provider,
                             "retrieved_at": a.retrieved_at})

    source_ids = set()
    if latest:
        source_ids |= set(latest.data_quality.get("odds_sources", []))
    if f.kickoff_source_record_id:
        source_ids.add(f.kickoff_source_record_id)
    sources = [{"id": s.id, "provider": s.provider, "resource": s.resource, "retrieved_at": s.retrieved_at,
                "trust_level": s.trust_level, "verification": s.verification}
               for s in db.scalars(select(SourceRecord).where(SourceRecord.id.in_(source_ids)))] if source_ids else []

    history = [{"id": p.id, "created_at": p.created_at, "trigger": p.trigger, "lineup_status": p.lineup_status,
                "one_x_two": p.markets.get("1x2"), "classification": p.classification,
                "reliability": p.reliability["score"], "change_summary": p.change_summary} for p in preds]
    data_quality = latest.data_quality if latest else {"note": "no prediction yet"}
    data_quality = {**data_quality, "result_available": f.result is not None,
                    "kickoff_source": next((s["provider"] for s in sources if s["id"] == f.kickoff_source_record_id),
                                           None)}
    return FixtureAnalysis(
        fixture=fixture_out(f, latest), prediction=prediction_detail(latest) if latest else None,
        prediction_history=history,
        form={"home": {"summary": summarise_form(home_recent), "matches": home_recent},
              "away": {"summary": summarise_form(away_recent), "matches": away_recent}},
        head_to_head=head_to_head(db, f.home_team_id, f.away_team_id, cutoff),
        standings_context={"home": ctx.get(f.home_team_id), "away": ctx.get(f.away_team_id),
                           "teams": len(table), "computed_from": "stored results before kickoff"},
        availability=availability, lineups=_lineups(db, f.id), odds=_odds_payload(db, f),
        data_quality=data_quality, sources=sources, disclaimer=DISCLAIMER,
    )



@router.get("/{fixture_id}/ai-analysis")
def get_ai_analysis(fixture_id: int, db: Session = Depends(get_db)) -> dict:
    f = _get_fixture(db, fixture_id)
    svc = AiAnalysisService(db, get_settings())
    latest = svc.latest(f.id)
    return {"configured": svc.configured,
            "available": f.status == "scheduled" and f.kickoff_utc > datetime.now(timezone.utc),
            "analysis": analysis_out(latest) if latest else None,
            "note": "Written by an AI model from the platform's evidence and web search. Advisory only: it does "
                    "not change the model's probabilities or picks, and its own numbers are not validated."}


@router.post("/{fixture_id}/ai-analysis")
def create_ai_analysis(fixture_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)) -> dict:
    f = _get_fixture(db, fixture_id)
    svc = AiAnalysisService(db, get_settings())
    if not svc.configured:
        raise HTTPException(503, "AI analysis is not configured on this server")
    try:
        row = svc.analyse(f, trigger="manual", requested_by=user.email)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except AiUnavailable as exc:
        raise HTTPException(503, "All AI API keys are busy or out of quota; try again later") from exc
    audit(db, user.email, "ai_analysis.create", f"fixture:{f.id}", {"analysis_id": row.id, "status": row.status})
    return analysis_out(row)

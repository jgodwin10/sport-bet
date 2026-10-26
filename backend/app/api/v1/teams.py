from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import AvailabilityReport, Competition, Fixture, Team
from app.db.session import get_db
from app.engine.pipeline import ModelSuite, SuiteConfig
from app.services.analytics import load_records, summarise_form, team_recent
from app.services.crests import crest_url, fetch_crest

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("")
def list_teams(db: Session = Depends(get_db), search: str | None = Query(default=None, max_length=80),
               competition: str | None = None, limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    q = select(Team).order_by(Team.name)
    if search:
        q = q.where(Team.name.ilike(f"%{search}%"))
    if competition:
        comp_id = db.scalar(select(Competition.id).where(Competition.code == competition))
        q = q.where(or_(Team.id.in_(select(Fixture.home_team_id).where(Fixture.competition_id == comp_id)),
                        Team.id.in_(select(Fixture.away_team_id).where(Fixture.competition_id == comp_id))))
    return [{"id": t.id, "name": t.name, "logo_url": crest_url(t)} for t in db.scalars(q.limit(limit))]


@router.get("/{team_id}/crest", responses={200: {"content": {"image/png": {}}}, 404: {}})
def team_crest(team_id: int, request: Request, size: str = Query("tiny", pattern="^(tiny|small)$"),
               db: Session = Depends(get_db)) -> Response:
    """Club crest served from our cache (downloaded once from the crest provider)."""
    team = db.get(Team, team_id)
    if team is None or not team.logo_url:
        raise HTTPException(404, "no crest for this team")
    crest = fetch_crest(db, team, size)
    if crest is None:
        raise HTTPException(404, "crest unavailable")
    etag = f'"{team_id}-{size}-{crest.fetched_at.timestamp():.0f}"'
    headers = {"Cache-Control": "public, max-age=604800, stale-while-revalidate=86400", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=crest.content, media_type=crest.content_type, headers=headers)


@router.get("/{team_id}/statistics")
def team_statistics(team_id: int, db: Session = Depends(get_db)) -> dict:
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(404, "team not found")
    now = datetime.now(timezone.utc)
    recent = team_recent(db, team_id, now, limit=40)
    comp = db.scalar(select(Fixture.competition_id).where(
        or_(Fixture.home_team_id == team_id, Fixture.away_team_id == team_id))
        .order_by(Fixture.kickoff_utc.desc()).limit(1))
    elo_history = []
    if comp:
        # Replay the competition's Elo to get this team's trajectory (read-only, no fitting)
        suite = ModelSuite(SuiteConfig(), pool=str(comp))
        key = str(team_id)
        for r in load_records(db, comp, before=now):
            suite.absorb(r)
            if key in (r.home, r.away):
                elo_history.append({"date": r.kickoff.date().isoformat(),
                                    "rating": round(suite.elo.ratings[suite.pool][key], 1)})
    upcoming = list(db.scalars(select(Fixture).where(
        or_(Fixture.home_team_id == team_id, Fixture.away_team_id == team_id), Fixture.kickoff_utc > now)
        .order_by(Fixture.kickoff_utc).limit(5)))
    availability = db.scalars(select(AvailabilityReport).where(AvailabilityReport.team_id == team_id)
                              .order_by(AvailabilityReport.retrieved_at.desc()).limit(30))
    return {
        "team": {"id": team.id, "name": team.name, "logo_url": crest_url(team)},
        "form": summarise_form(recent), "matches": recent,
        "xg_trend": [{"date": m["date"][:10], "xg_for": m["xg_for"], "xg_against": m["xg_against"],
                      "goals_for": m["goals_for"], "goals_against": m["goals_against"]} for m in reversed(recent)],
        "elo_history": elo_history[-120:],
        "upcoming": [{"fixture_id": f.id, "kickoff_utc": f.kickoff_utc, "home_team": f.home_team.name,
                      "away_team": f.away_team.name, "home_logo": crest_url(f.home_team),
                      "away_logo": crest_url(f.away_team)} for f in upcoming],
        "availability": [{"player": a.player_name, "kind": a.kind, "reason": a.reason,
                          "verification": a.verification, "retrieved_at": a.retrieved_at} for a in availability],
    }

"""Attach club crest URLs to teams. Misses are recorded (logo_checked_at) and
retried after a week; nothing is guessed — unmatched teams keep initials."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Competition, Fixture, Team, TeamAlias
from app.ingestion.competitions import COMPETITIONS
from app.ingestion.teams import CURATED_ALIASES
from app.providers.base import ProviderError
from app.providers.thesportsdb import LEAGUES, TheSportsDb, best_match
from app.services.crests import warm_crests

log = logging.getLogger(__name__)
RETRY_MISSES_AFTER = timedelta(days=7)


def candidate_names(db: Session, team: Team) -> list[str]:
    names = [team.name, *db.scalars(select(TeamAlias.alias).where(TeamAlias.team_id == team.id))]
    names += CURATED_ALIASES.get(team.name, [])
    seen, out = set(), []
    for n in names:
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    # Most specific (longest) names first: "Newcastle United" is a safer search than "Newcastle".
    return sorted(out, key=len, reverse=True)


def team_competition(db: Session, team_id: int) -> str | None:
    return db.scalar(select(Competition.code).join(Fixture, Fixture.competition_id == Competition.id)
                     .where(or_(Fixture.home_team_id == team_id, Fixture.away_team_id == team_id))
                     .order_by(Fixture.kickoff_utc.desc()).limit(1))


def refresh_logos(db: Session, provider: TheSportsDb, limit: int | None = None, force: bool = False) -> dict:
    now = datetime.now(timezone.utc)
    q = select(Team)
    if not force:
        q = q.where(or_(Team.logo_checked_at.is_(None),
                        (Team.logo_url.is_(None)) & (Team.logo_checked_at < now - RETRY_MISSES_AFTER)))
    teams = list(db.scalars(q.order_by(Team.id)))[: limit or None]
    stats = {"checked": 0, "found": 0, "missing": [], "errors": 0}
    by_comp: dict[str | None, list[Team]] = {}
    for t in teams:
        by_comp.setdefault(team_competition(db, t.id), []).append(t)

    for comp, comp_teams in by_comp.items():
        league = LEAGUES.get(comp or "")
        country = COMPETITIONS[comp].country if comp in COMPETITIONS else None
        listing: list[dict] = []
        if league:
            try:
                listing = provider.league_teams(comp)
            except ProviderError as exc:
                log.warning("crest league listing failed for %s: %s", comp, exc)
        for team in comp_teams:
            names = candidate_names(db, team)
            crest = best_match(listing, names, league, country)
            if crest is None:
                for name in names[:3]:  # canonical name first, then aliases from other providers
                    try:
                        crest = best_match(provider.search(name), names, league, country)
                    except ProviderError as exc:
                        log.warning("crest search failed for %s: %s", name, exc)
                        stats["errors"] += 1
                        break
                    if crest:
                        break
            team.logo_checked_at = now
            stats["checked"] += 1
            if crest:
                team.logo_url, team.logo_source = crest.url, provider.name
                stats["found"] += 1
            else:
                team.logo_url = team.logo_source = None  # never keep a crest we can no longer verify
                stats["missing"].append(team.name)
            db.commit()
    # Download small renditions now so no visitor ever waits on the third-party CDN.
    stats["cached_images"] = warm_crests(db, list(db.scalars(select(Team).where(Team.logo_url.is_not(None)))))
    return stats

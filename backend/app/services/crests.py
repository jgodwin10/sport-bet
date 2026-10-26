"""Crest image cache: fetch a provider rendition once, store the bytes, serve them ourselves."""

from __future__ import annotations

import logging

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Team, TeamCrest

log = logging.getLogger(__name__)
SIZES = {"tiny": "/tiny", "small": "/small"}  # TheSportsDB renditions: 100px and 200px
MAX_BYTES = 400_000


def crest_url(team: Team) -> str | None:
    """Public URL for a team's crest (served by our API), or None when we have no crest."""
    return f"/api/v1/teams/{team.id}/crest" if team.logo_url else None


def fetch_crest(db: Session, team: Team, size: str, client: httpx.Client | None = None) -> TeamCrest | None:
    if not team.logo_url or size not in SIZES:
        return None
    cached = db.get(TeamCrest, (team.id, size))
    if cached and cached.source_url == team.logo_url:
        return cached
    url = team.logo_url + (SIZES[size] if team.logo_source == "thesportsdb" else "")
    own = client is None
    client = client or httpx.Client(timeout=45, follow_redirects=True)
    try:
        resp = client.get(url)
    except httpx.HTTPError as exc:
        log.warning("crest download failed for team %s: %s", team.id, exc)
        return None
    finally:
        if own:
            client.close()
    ctype = resp.headers.get("content-type", "")
    if resp.status_code != 200 or not ctype.startswith("image/") or len(resp.content) > MAX_BYTES:
        log.warning("crest for team %s rejected: HTTP %s %s %dB", team.id, resp.status_code, ctype, len(resp.content))
        return None
    if cached:
        cached.content, cached.content_type, cached.source_url = resp.content, ctype, team.logo_url
    else:
        cached = TeamCrest(team_id=team.id, size=size, content=resp.content, content_type=ctype, source_url=team.logo_url)
        db.add(cached)
    try:
        db.commit()
    except IntegrityError:  # stored concurrently, e.g. by a visitor's request while the logos job warms the cache
        db.rollback()
        return db.get(TeamCrest, (team.id, size))
    return cached


def warm_crests(db: Session, teams: list[Team]) -> int:
    n = 0
    with httpx.Client(timeout=45, follow_redirects=True) as client:
        for team in teams:
            for size in SIZES:
                if fetch_crest(db, team, size, client) is not None:
                    n += 1
    return n

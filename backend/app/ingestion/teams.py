"""Team identity resolution across providers.

football-data.co.uk names are canonical (it is the history source). Other
providers' names resolve through, in order: a stored alias, a curated alias
list, then a conservative fuzzy match restricted to teams in the same
competition. Ambiguous names are recorded as unresolved conflicts and skipped -
we never guess which team a provider meant.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Competition, DataConflict, Fixture, Team, TeamAlias

CANONICAL_PROVIDER = "football_data_co_uk"

_STOP = {
    "fc", "afc", "cf", "sc", "ac", "ssc", "as", "sv", "vfb", "vfl", "tsg", "fsv", "rc", "ogc", "sco", "cd",
    "ud", "rcd", "sd", "ca", "us", "ss", "bc", "club", "calcio", "de", "1", "1899", "1900", "1846", "04",
    "05", "1910", "1913", "kv", "krc", "rsc", "royal", "sk", "fk", "bk", "cfc", "hsc", "ssv", "tsv",
}
_TOKEN_MAP = {"utd": "united", "man": "manchester", "nottm": "nottingham", "st": "saint", "ath": "athletic"}

# Curated aliases: canonical (football-data.co.uk) name -> names used elsewhere.
CURATED_ALIASES: dict[str, list[str]] = {
    "Man United": ["Manchester United", "Manchester United FC", "Man Utd"],
    "Man City": ["Manchester City", "Manchester City FC"],
    "Nott'm Forest": ["Nottingham Forest", "Nottingham"],
    "Wolves": ["Wolverhampton Wanderers", "Wolverhampton"],
    "Tottenham": ["Tottenham Hotspur", "Spurs"],
    "Newcastle": ["Newcastle United"],
    "West Ham": ["West Ham United"],
    "Brighton": ["Brighton and Hove Albion", "Brighton & Hove Albion"],
    "Leeds": ["Leeds United"],
    "Sheffield United": ["Sheffield Utd", "Sheffield Utd."],
    "Sheffield Weds": ["Sheffield Wednesday"],
    "QPR": ["Queens Park Rangers"],
    "West Brom": ["West Bromwich Albion"],
    "Ath Madrid": ["Atletico Madrid", "Atlético Madrid", "Club Atlético de Madrid"],
    "Ath Bilbao": ["Athletic Bilbao", "Athletic Club"],
    "Sociedad": ["Real Sociedad"],
    "Betis": ["Real Betis"],
    "Celta": ["Celta Vigo", "RC Celta"],
    "Espanol": ["Espanyol", "RCD Espanyol"],
    "Vallecano": ["Rayo Vallecano"],
    "Ein Frankfurt": ["Eintracht Frankfurt"],
    "M'gladbach": ["Borussia Monchengladbach", "Borussia Mönchengladbach", "Gladbach"],
    "Bayern Munich": ["Bayern München", "FC Bayern München", "Bayern"],
    "Leverkusen": ["Bayer Leverkusen", "Bayer 04 Leverkusen"],
    "Dortmund": ["Borussia Dortmund"],
    "FC Koln": ["1. FC Köln", "FC Cologne", "Köln"],
    "Inter": ["Inter Milan", "Internazionale", "FC Internazionale Milano"],
    "Milan": ["AC Milan"],
    "Roma": ["AS Roma"],
    "Paris SG": ["Paris Saint Germain", "Paris Saint-Germain", "PSG"],
    "St Etienne": ["Saint Etienne", "Saint-Étienne", "AS Saint-Étienne"],
}


def normalize(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ").replace("'", "")
    tokens = re.split(r"[^a-z0-9]+", text)
    tokens = [_TOKEN_MAP.get(t, t) for t in tokens if t]
    kept = [t for t in tokens if t not in _STOP]
    return " ".join(kept or tokens)


_CURATED_INDEX = {normalize(alias): normalize(canon) for canon, aliases in CURATED_ALIASES.items()
                  for alias in aliases}


def similarity(a: str, b: str) -> float:
    score = SequenceMatcher(None, a, b).ratio()
    if a and b and (set(a.split()) <= set(b.split()) or set(b.split()) <= set(a.split())):
        score = max(score, 0.9)
    return score


class TeamResolver:
    """Resolution order for a (provider, name):
    1. exact alias previously stored for this provider;
    2. unique team whose stored aliases share the normalised/curated form;
    3. unique high-confidence fuzzy match among the competition's teams;
    4. fixture-source providers create a new team; others record an unresolved conflict.

    Invariant: a provider uses one name per team, so a team that already has an
    alias from this provider is never a candidate for a *different* name from it.
    This stops e.g. "Town 04" and "Town 05" (same normalised form) being merged.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._cache: dict[tuple[str, str], int | None] = {}

    def resolve(self, provider: str, name: str, competition_code: str | None = None,
                provider_team_id: str | None = None, can_create: bool = False) -> int | None:
        key = (provider, name)
        if key not in self._cache:
            self._cache[key] = self._resolve(provider, name, normalize(name), competition_code, provider_team_id,
                                             can_create or provider == CANONICAL_PROVIDER)
        return self._cache[key]

    def _alias(self, team_id: int, provider: str, name: str, norm: str, provider_team_id: str | None) -> None:
        self.db.add(TeamAlias(team_id=team_id, provider=provider, alias=name, normalized=norm,
                              provider_team_id=provider_team_id))
        self.db.flush()

    def _taken(self, provider: str) -> set[int]:
        return set(self.db.scalars(select(TeamAlias.team_id).where(TeamAlias.provider == provider)))

    def _resolve(self, provider: str, name: str, norm: str, competition_code: str | None,
                 provider_team_id: str | None, can_create: bool) -> int | None:
        hit = self.db.scalar(select(TeamAlias.team_id).where(TeamAlias.provider == provider, TeamAlias.alias == name))
        if hit:
            return hit
        taken = self._taken(provider)

        targets = {norm, _CURATED_INDEX.get(norm, norm)}
        matches = set(self.db.scalars(select(TeamAlias.team_id).where(TeamAlias.normalized.in_(targets)))) - taken
        if len(matches) == 1:
            team_id = matches.pop()
            self._alias(team_id, provider, name, norm, provider_team_id)
            return team_id

        scored = []
        if not matches:  # several exact normalised matches = ambiguous; skip fuzzy
            candidates = [t for t in self._competition_teams(competition_code) if t.id not in taken]
            scored = sorted(((similarity(norm, normalize(t.name)), t.id, t.name) for t in candidates), reverse=True)
            if scored and scored[0][0] >= 0.85 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.08):
                self._alias(scored[0][1], provider, name, norm, provider_team_id)
                return scored[0][1]

        if can_create and not matches:
            team_name = name if self.db.scalar(select(Team.id).where(Team.name == name)) is None \
                else f"{name} ({provider})"
            team = Team(name=team_name)
            self.db.add(team)
            self.db.flush()
            self._alias(team.id, provider, name, norm, provider_team_id)
            return team.id

        self.db.add(DataConflict(
            entity_type="team_mapping", entity_id=None, field="name", material=False,
            values=[{"provider": provider, "value": name, "competition": competition_code,
                     "candidates": [{"team": n, "score": round(sc, 3)} for sc, _, n in scored[:3]]
                     or [{"team_id": t} for t in sorted(matches)]}],
            resolution="unresolved: add a team alias to map this name",
        ))
        return None

    def _competition_teams(self, competition_code: str | None) -> list[Team]:
        q = select(Team)
        if competition_code:
            comp_id = self.db.scalar(select(Competition.id).where(Competition.code == competition_code))
            q = q.where(Team.id.in_(
                select(Fixture.home_team_id).where(Fixture.competition_id == comp_id)
            ) | Team.id.in_(select(Fixture.away_team_id).where(Fixture.competition_id == comp_id)))
        return list(self.db.scalars(q))


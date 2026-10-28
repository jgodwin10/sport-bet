"""TheSportsDB adapter — club crests only.

Free test key "123" (default) allows ~30 requests/minute and returns at most 10
teams per league listing, so lookups combine one league listing per competition
with per-team searches. Production use should set a premium THESPORTSDB_API_KEY.
Crests are the clubs' trademarks; they are displayed for identification only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.ingestion.teams import normalize, similarity
from app.providers.base import ProviderError
from app.providers.http import ProviderHttpClient

PROVIDER = "thesportsdb"
BASE_URL = "https://www.thesportsdb.com/api/v1/json"

# Our competition code -> TheSportsDB league name (used for listings and as a match preference).
LEAGUES = {
    "ENG-1": "English Premier League", "ENG-2": "English League Championship", "ENG-3": "English League 1",
    "ENG-4": "English League 2", "SCO-1": "Scottish Premiership", "GER-1": "German Bundesliga",
    "GER-2": "German 2. Bundesliga", "ESP-1": "Spanish La Liga", "ESP-2": "Spanish La Liga 2",
    "ITA-1": "Italian Serie A", "ITA-2": "Italian Serie B", "FRA-1": "French Ligue 1", "FRA-2": "French Ligue 2",
    "NED-1": "Dutch Eredivisie", "BEL-1": "Belgian Pro League", "POR-1": "Portuguese Primeira Liga",
    "TUR-1": "Turkish Super Lig", "GRE-1": "Greek Superleague Greece", "ENG-5": "English National League",
    "SCO-2": "Scottish Championship", "SCO-3": "Scottish League 1", "SCO-4": "Scottish League 2",
}


@dataclass(frozen=True)
class Crest:
    url: str
    matched_name: str
    provider_id: str
    league: str | None
    score: float


def _eligible(t: dict) -> bool:
    return t.get("strSport") == "Soccer" and (t.get("strGender") or "Male") == "Male" and bool(t.get("strBadge"))


def _names(t: dict) -> list[str]:
    alts = [a.strip() for a in (t.get("strTeamAlternate") or "").split(",") if a.strip()]
    return [t["strTeam"], *alts, *([t["strTeamShort"]] if t.get("strTeamShort") else [])]


def best_match(candidates: list[dict], names: list[str], league: str | None, country: str | None = None) -> Crest | None:
    """Pick the crest whose name (or listed alternate) best matches any of our names.
    Requires a strong match and, when known, the same country — so "Newcastle" can never
    resolve to Australia's Newcastle Jets. A matching league adds a small preference."""
    wanted = {normalize(n) for n in names if n}
    best: Crest | None = None
    for t in filter(_eligible, candidates):
        if country and t.get("strCountry") and t["strCountry"] != country:
            continue
        score = max(similarity(w, normalize(n)) for w in wanted for n in _names(t))
        if league and t.get("strLeague") == league:
            score += 0.05
        if score >= 0.88 and (best is None or score > best.score):
            best = Crest(t["strBadge"], t["strTeam"], str(t.get("idTeam")), t.get("strLeague"), score)
    return best


class TheSportsDb:
    name = PROVIDER
    trust_level = 60

    def __init__(self, api_key: str = "123", client: ProviderHttpClient | None = None) -> None:
        self.api_key = api_key
        # ~30 requests/minute on the free key; the client also honours Retry-After on 429.
        self.client = client or ProviderHttpClient(PROVIDER, min_interval_seconds=2.2, max_retries=3, backoff_base=5)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def capabilities(self) -> dict[str, object]:
        return {"requires_key": False, "crests": True, "rate_limit": "~30 requests/minute on the free test key",
                "note": "free key lists at most 10 teams per league"}

    def _get(self, resource: str, params: dict) -> list[dict]:
        res = self.client.get(f"{BASE_URL}/{self.api_key}/{resource}", params=params, cache_ttl=3600)
        try:
            payload = json.loads(res.content)
        except ValueError as exc:
            raise ProviderError(f"{self.name}: non-JSON response from {resource}") from exc
        return payload.get("teams") or []

    def league_teams(self, competition_code: str) -> list[dict]:
        league = LEAGUES.get(competition_code)
        return self._get("search_all_teams.php", {"l": league}) if league else []

    def search(self, name: str) -> list[dict]:
        return self._get("searchteams.php", {"t": name.replace(" ", "_")})

"""football-data.org v4 adapter (API key required; free tier covers the major
leagues with a 10 requests/minute limit). Used as the authoritative source for
kickoff times (UTC) and match status, including postponements."""

from __future__ import annotations

import json
from datetime import date, datetime

from app.engine.elo import season_of
from app.ingestion.competitions import BY_FDORG, COMPETITIONS
from app.providers.base import NormalizedFixture, ProviderBatch, ProviderNotConfigured
from app.providers.http import ProviderHttpClient

PROVIDER = "football_data_org"
BASE_URL = "https://api.football-data.org/v4"

STATUS_MAP = {
    "SCHEDULED": "scheduled", "TIMED": "scheduled", "IN_PLAY": "live", "PAUSED": "live",
    "LIVE": "live", "FINISHED": "finished", "AWARDED": "finished", "POSTPONED": "postponed",
    "SUSPENDED": "abandoned", "CANCELLED": "cancelled",
}


def parse_matches(payload: dict, competition_code: str) -> list[NormalizedFixture]:
    out = []
    for m in payload.get("matches", []):
        kickoff = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
        status = STATUS_MAP.get(m.get("status", ""), "scheduled")
        full = (m.get("score") or {}).get("fullTime") or {}
        half = (m.get("score") or {}).get("halfTime") or {}
        referees = m.get("referees") or []
        fx = NormalizedFixture(
            provider=PROVIDER,
            provider_fixture_id=str(m["id"]),
            competition_code=competition_code,
            season_label=season_of(kickoff.date()),
            home_name=m["homeTeam"].get("shortName") or m["homeTeam"]["name"],
            away_name=m["awayTeam"].get("shortName") or m["awayTeam"]["name"],
            kickoff_utc=kickoff,
            status=status,
            stage="league" if m.get("stage") in (None, "REGULAR_SEASON") else "cup",
            venue=m.get("venue"),
            referee=referees[0].get("name") if referees else None,
        )
        if status == "finished" and full.get("home") is not None:
            fx.home_goals, fx.away_goals = full["home"], full["away"]
            fx.ht_home_goals, fx.ht_away_goals = half.get("home"), half.get("away")
        out.append(fx)
    return out


class FootballDataOrg:
    name = PROVIDER
    trust_level = 85  # official-feed derived kickoff times and statuses

    def __init__(self, api_key: str | None, client: ProviderHttpClient | None = None) -> None:
        self.api_key = api_key
        self.client = client or ProviderHttpClient(PROVIDER, min_interval_seconds=6.5)  # 10 req/min

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def capabilities(self) -> dict[str, object]:
        return {
            "requires_key": True,
            "fixtures": True, "results": True, "status": True, "standings": True,
            "odds": False, "injuries": False, "lineups": "paid tiers only",
            "competitions": sorted(BY_FDORG[c].code for c in BY_FDORG),
            "rate_limit": "10 requests/minute on free tier",
        }

    def matches(self, competition_code: str, date_from: date, date_to: date) -> ProviderBatch:
        if not self.configured:
            raise ProviderNotConfigured("FOOTBALL_DATA_ORG_API_KEY is not set")
        comp = COMPETITIONS[competition_code]
        if not comp.fdorg:
            raise ValueError(f"{competition_code} not covered by {self.name}")
        resource = f"/competitions/{comp.fdorg}/matches"
        res = self.client.get(BASE_URL + resource,
                              params={"dateFrom": date_from.isoformat(), "dateTo": date_to.isoformat()},
                              headers={"X-Auth-Token": self.api_key or ""}, cache_ttl=300)
        payload = json.loads(res.content)
        return ProviderBatch(self.name, resource, res.retrieved_at, res.sha256, self.trust_level,
                             parse_matches(payload, competition_code))

"""API-Football (api-sports.io) v3 adapter for injuries/suspensions and lineups.

API key required (free plan: 100 requests/day). Lineups published by the API are
the official team sheets (normally ~20-40 minutes before kickoff) and are marked
`confirmed`; there is no projected-lineup endpoint, so before then the lineup
status remains `unavailable` rather than being guessed.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from app.ingestion.competitions import COMPETITIONS
from app.providers.base import (
    NormalizedAvailability, NormalizedFixture, NormalizedLineup, ProviderBatch, ProviderNotConfigured,
)
from app.providers.http import ProviderHttpClient
from app.engine.elo import season_of

PROVIDER = "api_football"
BASE_URL = "https://v3.football.api-sports.io"
SUSPENSION_WORDS = ("suspend", "red card", "yellow card")


def parse_injuries(payload: dict) -> list[NormalizedAvailability]:
    out = []
    for item in payload.get("response", []):
        player = item.get("player") or {}
        reason = player.get("reason")
        kind_raw = (player.get("type") or "").lower()
        if kind_raw == "questionable":
            kind = "doubtful"
        elif reason and any(w in reason.lower() for w in SUSPENSION_WORDS):
            kind = "suspension"
        else:
            kind = "injury"
        out.append(NormalizedAvailability(
            team_name=item["team"]["name"], player_name=player.get("name") or "unknown", kind=kind,
            # Aggregated reports, not club announcements: never upgraded to "confirmed"
            verification="reported", reason=reason,
            provider_fixture_id=str((item.get("fixture") or {}).get("id")),
        ))
    return out


def parse_lineups(payload: dict) -> list[NormalizedLineup]:
    out = []
    for item in payload.get("response", []):
        players = [
            {"name": p["player"]["name"], "number": p["player"].get("number"), "position": p["player"].get("pos"),
             "starter": starter}
            for key, starter in (("startXI", True), ("substitutes", False))
            for p in item.get(key) or []
        ]
        out.append(NormalizedLineup(team_name=item["team"]["name"], status="confirmed",
                                    formation=item.get("formation"), players=players))
    return out


def parse_fixtures(payload: dict, competition_code: str) -> list[NormalizedFixture]:
    status_map = {"NS": "scheduled", "TBD": "scheduled", "PST": "postponed", "CANC": "cancelled",
                  "ABD": "abandoned", "FT": "finished", "AET": "finished", "PEN": "finished"}
    out = []
    for item in payload.get("response", []):
        fx, teams = item["fixture"], item["teams"]
        kickoff = datetime.fromisoformat(fx["date"])
        out.append(NormalizedFixture(
            provider=PROVIDER, provider_fixture_id=str(fx["id"]), competition_code=competition_code,
            season_label=season_of(kickoff.date()), home_name=teams["home"]["name"],
            away_name=teams["away"]["name"], kickoff_utc=kickoff,
            status=status_map.get(fx["status"]["short"], "live"),
            venue=(fx.get("venue") or {}).get("name"), referee=fx.get("referee"),
        ))
    return out


class ApiFootball:
    name = PROVIDER
    trust_level = 75

    def __init__(self, api_key: str | None, client: ProviderHttpClient | None = None) -> None:
        self.api_key = api_key
        self.client = client or ProviderHttpClient(PROVIDER, min_interval_seconds=6.5)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def capabilities(self) -> dict[str, object]:
        return {
            "requires_key": True, "fixtures": True, "injuries": "reported absences per fixture",
            "lineups": "official lineups shortly before kickoff", "odds": "not used",
            "rate_limit": "100 requests/day on free plan",
        }

    def _get(self, resource: str, params: dict[str, object]):
        if not self.configured:
            raise ProviderNotConfigured("API_FOOTBALL_KEY is not set")
        return self.client.get(BASE_URL + resource, params=params,
                               headers={"x-apisports-key": self.api_key or ""}, cache_ttl=120)

    def fixtures(self, competition_code: str, date_from: date, date_to: date) -> ProviderBatch:
        league = COMPETITIONS[competition_code].api_football
        season = int(season_of(date_from).split("-")[0])
        res = self._get("/fixtures", {"league": league, "season": season, "from": date_from.isoformat(),
                                      "to": date_to.isoformat()})
        return ProviderBatch(self.name, "/fixtures", res.retrieved_at, res.sha256, self.trust_level,
                             parse_fixtures(json.loads(res.content), competition_code))

    def injuries(self, provider_fixture_id: str) -> ProviderBatch:
        res = self._get("/injuries", {"fixture": provider_fixture_id})
        return ProviderBatch(self.name, "/injuries", res.retrieved_at, res.sha256, self.trust_level,
                             availability=parse_injuries(json.loads(res.content)))

    def lineups(self, provider_fixture_id: str) -> ProviderBatch:
        res = self._get("/fixtures/lineups", {"fixture": provider_fixture_id})
        return ProviderBatch(self.name, "/fixtures/lineups", res.retrieved_at, res.sha256, 90,
                             lineups=parse_lineups(json.loads(res.content)))

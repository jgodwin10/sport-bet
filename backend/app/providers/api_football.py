"""API-Football (api-sports.io) v3 adapter for injuries/suspensions, lineups and
cup history.

API key required (free plan: 100 requests/day, and only some past seasons). Lineups published by the API are
the official team sheets (normally ~20-40 minutes before kickoff) and are marked
`confirmed`; there is no projected-lineup endpoint, so before then the lineup
status remains `unavailable` rather than being guessed.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from app.ingestion.competitions import COMPETITIONS
from app.providers.base import (
    NormalizedAvailability, NormalizedFixture, NormalizedLineup, ProviderBatch, ProviderError, ProviderNotConfigured,
)
from app.providers.http import ProviderHttpClient
from app.engine.elo import season_of

PROVIDER = "api_football"
BASE_URL = "https://v3.football.api-sports.io"
SUSPENSION_WORDS = ("suspend", "red card", "yellow card")
# Seasons the plan refused in this process; the refusal is plan-wide, so don't spend requests asking again.
_DENIED_SEASONS: set[int] = set()


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
        nf = NormalizedFixture(
            provider=PROVIDER, provider_fixture_id=str(fx["id"]), competition_code=competition_code,
            season_label=season_of(kickoff.date()), home_name=teams["home"]["name"],
            away_name=teams["away"]["name"], kickoff_utc=kickoff,
            status=status_map.get(fx["status"]["short"], "live"),
            venue=(fx.get("venue") or {}).get("name"), referee=fx.get("referee"),
            stage=COMPETITIONS[competition_code].format,
        )
        # Bets settle on 90 minutes, so extra time and penalties are left out
        full_time = (item.get("score") or {}).get("fulltime") or {}
        if nf.status == "finished" and full_time.get("home") is not None and full_time.get("away") is not None:
            nf.home_goals, nf.away_goals = int(full_time["home"]), int(full_time["away"])
            half_time = item["score"].get("halftime") or {}
            nf.ht_home_goals, nf.ht_away_goals = half_time.get("home"), half_time.get("away")
        out.append(nf)
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

    def _fixtures(self, competition_code: str, season: int, params: dict[str, object]) -> ProviderBatch:
        league = COMPETITIONS[competition_code].api_football
        if not league:
            raise ValueError(f"{competition_code} not covered by {self.name}")
        if season in _DENIED_SEASONS:
            raise ProviderError(f"{self.name}: season {season} not available on this plan")
        res = self._get("/fixtures", {"league": league, "season": season, **params})
        payload = json.loads(res.content)
        errors = payload.get("errors")
        if errors:
            if isinstance(errors, dict) and "plan" in errors:
                _DENIED_SEASONS.add(season)
            raise ProviderError(f"{self.name}: {errors}")
        return ProviderBatch(self.name, "/fixtures", res.retrieved_at, res.sha256, self.trust_level,
                             parse_fixtures(payload, competition_code))

    def fixtures(self, competition_code: str, date_from: date, date_to: date) -> ProviderBatch:
        season = int(season_of(date_from).split("-")[0])
        return self._fixtures(competition_code, season, {"from": date_from.isoformat(), "to": date_to.isoformat()})

    def season(self, competition_code: str, start_year: int) -> ProviderBatch:
        """Every fixture of one season, with 90-minute results (one request)."""
        return self._fixtures(competition_code, start_year, {})

    def injuries(self, provider_fixture_id: str) -> ProviderBatch:
        res = self._get("/injuries", {"fixture": provider_fixture_id})
        return ProviderBatch(self.name, "/injuries", res.retrieved_at, res.sha256, self.trust_level,
                             availability=parse_injuries(json.loads(res.content)))

    def lineups(self, provider_fixture_id: str) -> ProviderBatch:
        res = self._get("/fixtures/lineups", {"fixture": provider_fixture_id})
        return ProviderBatch(self.name, "/fixtures/lineups", res.retrieved_at, res.sha256, 90,
                             lineups=parse_lineups(json.loads(res.content)))

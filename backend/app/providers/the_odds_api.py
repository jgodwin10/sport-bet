"""The Odds API v4 adapter (API key required; usage is metered in credits:
each call costs markets x regions credits, free tier = 500 credits/month).
Provides live pre-match 1X2 (h2h) and totals prices from many bookmakers with
per-bookmaker update timestamps."""

from __future__ import annotations

import json
from datetime import datetime

from app.engine.elo import season_of
from app.ingestion.competitions import BY_ODDS_API, COMPETITIONS
from app.providers.base import NormalizedFixture, NormalizedOdds, ProviderBatch, ProviderNotConfigured
from app.providers.http import ProviderHttpClient

PROVIDER = "the_odds_api"
BASE_URL = "https://api.the-odds-api.com/v4"


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_events(payload: list[dict], competition_code: str) -> list[NormalizedFixture]:
    out = []
    for ev in payload:
        kickoff = _ts(ev["commence_time"])
        home, away = ev["home_team"], ev["away_team"]
        odds: list[NormalizedOdds] = []
        for bk in ev.get("bookmakers", []):
            for market in bk.get("markets", []):
                observed = _ts(market.get("last_update") or bk["last_update"])
                for o in market.get("outcomes", []):
                    if market["key"] == "h2h":
                        sel = "home" if o["name"] == home else "away" if o["name"] == away else "draw"
                        odds.append(NormalizedOdds(bk["key"], bk["title"], "1x2", sel, float(o["price"]),
                                                   "pre_match", observed))
                    elif market["key"] == "totals" and o.get("point") is not None:
                        odds.append(NormalizedOdds(bk["key"], bk["title"], "totals", o["name"].lower(),
                                                   float(o["price"]), "pre_match", observed, float(o["point"])))
        out.append(NormalizedFixture(
            provider=PROVIDER, provider_fixture_id=ev["id"], competition_code=competition_code,
            season_label=season_of(kickoff.date()), home_name=home, away_name=away, kickoff_utc=kickoff,
            status="scheduled", odds=odds,
        ))
    return out


class TheOddsApi:
    name = PROVIDER
    trust_level = 80

    def __init__(self, api_key: str | None, regions: str = "uk,eu", client: ProviderHttpClient | None = None):
        self.api_key = api_key
        self.regions = regions
        self.client = client or ProviderHttpClient(PROVIDER, min_interval_seconds=1.0)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def capabilities(self) -> dict[str, object]:
        return {
            "requires_key": True, "odds": "pre-match 1X2 and totals, many bookmakers, timestamped",
            "fixtures": "only events with prices", "results": False, "injuries": False, "lineups": False,
            "competitions": sorted(BY_ODDS_API[k].code for k in BY_ODDS_API),
            "cost": "markets x regions credits per call",
        }

    def odds(self, competition_code: str) -> ProviderBatch:
        if not self.configured:
            raise ProviderNotConfigured("THE_ODDS_API_KEY is not set")
        sport = COMPETITIONS[competition_code].odds_api
        if not sport:
            raise ValueError(f"{competition_code} not covered by {self.name}")
        resource = f"/sports/{sport}/odds"
        res = self.client.get(BASE_URL + resource, params={
            "apiKey": self.api_key, "regions": self.regions, "markets": "h2h,totals",
            "oddsFormat": "decimal", "dateFormat": "iso",
        }, cache_ttl=300)
        payload = json.loads(res.content)
        return ProviderBatch(self.name, resource, res.retrieved_at, res.sha256, self.trust_level,
                             parse_events(payload, competition_code),
                             meta={"requests_remaining": res.headers.get("x-requests-remaining")})

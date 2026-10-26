from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.core.config import Settings, get_settings
from app.providers.api_football import ApiFootball
from app.providers.football_data_co_uk import FootballDataCoUk
from app.providers.football_data_org import FootballDataOrg
from app.providers.http import ProviderHttpClient
from app.providers.the_odds_api import TheOddsApi
from app.providers.thesportsdb import TheSportsDb


def _secret(value) -> str | None:
    return value.get_secret_value() if value else None


@dataclass
class Providers:
    fdcuk: FootballDataCoUk
    fdorg: FootballDataOrg
    odds_api: TheOddsApi
    api_football: ApiFootball
    crests: TheSportsDb

    def all(self):
        return [self.fdcuk, self.fdorg, self.odds_api, self.api_football, self.crests]

    def status(self) -> list[dict[str, object]]:
        return [{"name": p.name, "configured": p.configured, "trust_level": p.trust_level,
                 "capabilities": p.capabilities()} for p in self.all()]


def build_providers(settings: Settings) -> Providers:
    def client(name: str, interval: float) -> ProviderHttpClient:
        return ProviderHttpClient(name, timeout=settings.provider_timeout_seconds,
                                  max_retries=settings.provider_max_retries, min_interval_seconds=interval)

    return Providers(
        fdcuk=FootballDataCoUk(settings.football_data_co_uk_base_url, client("football_data_co_uk", 1.0),
                               enabled=settings.football_data_co_uk_enabled),
        fdorg=FootballDataOrg(_secret(settings.football_data_org_api_key), client("football_data_org", 6.5)),
        odds_api=TheOddsApi(_secret(settings.the_odds_api_key), settings.the_odds_api_regions,
                            client("the_odds_api", 1.0)),
        api_football=ApiFootball(_secret(settings.api_football_key), client("api_football", 6.5)),
        crests=TheSportsDb(settings.thesportsdb_api_key),
    )


@lru_cache
def get_providers() -> Providers:
    return build_providers(get_settings())

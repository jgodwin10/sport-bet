"""Environment-based configuration. Secrets come only from the environment."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ingestion.competitions import COMPETITIONS, CUPS


def _names(raw: str) -> list[str]:
    return [m.strip() for m in raw.split(",") if m.strip()]


def _keys(secret: SecretStr | None) -> list[str]:
    raw = secret.get_secret_value() if secret else ""
    return list(dict.fromkeys(k.strip() for k in raw.replace("\n", ",").split(",") if k.strip()))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"  # development | test | production
    database_url: str = "postgresql+psycopg://footy:footy@localhost:5432/footy"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:5173"]
    log_level: str = "INFO"
    task_mode: str = "inline"  # celery | inline (thread in the API process; dev only)

    # Auth
    jwt_secret: SecretStr = SecretStr("change-me-in-production")
    jwt_ttl_minutes: int = 120
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: SecretStr | None = None

    # Rate limiting (requests per minute per client IP)
    rate_limit_per_minute: int = 120

    # Providers. Keys are optional: adapters without credentials report themselves
    # as unconfigured and the platform keeps working with the remaining sources.
    football_data_co_uk_enabled: bool = True
    football_data_co_uk_base_url: str = "https://www.football-data.co.uk"
    football_data_org_api_key: SecretStr | None = None
    the_odds_api_key: SecretStr | None = None
    the_odds_api_regions: str = "uk,eu"
    # Competitions priced from The Odds API (each refresh costs credits). Cups have no other odds
    # source. Leagues get odds from football-data.co.uk's weekly file, which only covers the next
    # round once it is published (Tuesdays and Fridays), so a league is priced here only while a
    # fixture in the window below has no odds at all.
    odds_api_competitions: list[str] = [c.code for c in COMPETITIONS.values() if c.odds_api]
    odds_api_days_ahead: int = 3  # only spend credits on competitions with a fixture this soon
    odds_api_refresh_hours: float = 20.0  # at most one priced call per competition in this many hours
    odds_api_credit_reserve: int = 30  # stop pricing when the month's remaining credits fall below this
    # Match day: a competition with a top pick kicking off within `odds_api_matchday_hours` is
    # re-priced when that pick's odds are older than `odds_api_matchday_refresh_hours`, so the pick is
    # not held back as stale. It only spends credits beyond `odds_api_daily_allowance` per day left
    # in the month (kept for routine pricing) on top of the reserve.
    odds_api_matchday_hours: float = 12.0
    odds_api_matchday_refresh_hours: float = 6.0
    odds_api_daily_allowance: int = 8
    api_football_key: SecretStr | None = None
    thesportsdb_api_key: str = "123"  # free test key; crests only
    provider_timeout_seconds: float = 20.0
    provider_max_retries: int = 3

    # AI match analysis (optional): providers are tried in this order, skipping any without keys.
    ai_providers: str = "openai,gemini"
    # OpenAI and Gemini keys: several may be given per provider, separated by commas; requests
    # rotate through them and skip keys that are rate-limited or rejected.
    openai_api_keys: SecretStr | None = None
    # Tried in order; a model the account cannot use falls through to the next.
    openai_models: str = "gpt-5-mini,gpt-4.1-mini"
    openai_timeout_seconds: float = 180.0  # web search plus reasoning can take a while
    gemini_api_keys: SecretStr | None = None
    # Tried in order; a model the API reports as unavailable (404) falls through to the next.
    gemini_models: str = "gemini-3.8-flash,gemini-flash-latest,gemini-flash-lite-latest"
    gemini_search_grounding: bool = True  # let the AI search the web for team news (either provider)
    gemini_timeout_seconds: float = 120.0
    # Scheduled analysis for fixtures kicking off within this many hours (0 disables it)
    gemini_auto_hours: int = 48
    gemini_auto_max_per_run: int = 10
    gemini_refresh_hours: float = 12.0  # re-analyse when the latest analysis is older than this

    @property
    def gemini_key_list(self) -> list[str]:
        return _keys(self.gemini_api_keys)

    @property
    def gemini_model_list(self) -> list[str]:
        return _names(self.gemini_models)

    @property
    def openai_key_list(self) -> list[str]:
        return _keys(self.openai_api_keys)

    @property
    def openai_model_list(self) -> list[str]:
        return _names(self.openai_models)

    @property
    def ai_provider_list(self) -> list[str]:
        return [n.lower() for n in _names(self.ai_providers)]

    # The calendar day a daily 2 odds slip covers is taken in this time zone
    two_odds_timezone: str = "UTC"

    # Competitions to track, by internal code (see app/ingestion/competitions.py)
    competitions: list[str] = [
        "ENG-1", "ENG-2", "ENG-3", "ENG-4", "ENG-5", "SCO-1", "SCO-2", "SCO-3", "SCO-4", "GER-1", "GER-2",
        "ESP-1", "ESP-2", "ITA-1", "ITA-2", "FRA-1", "FRA-2", "NED-1", "BEL-1", "POR-1", "TUR-1", "GRE-1",
        *CUPS,
    ]
    history_seasons: int = 4

    # Model hyper-parameters
    dc_half_life_days: float = 240.0
    dc_ridge: float = 2.0
    max_goals: int = 10

    # Schedules (minutes)
    fixtures_refresh_minutes: int = 360
    odds_refresh_minutes: int = 60
    lineup_check_minutes: int = 15
    lineup_window_minutes: int = 90
    stale_odds_hours: float = 12.0

    responsible_gambling_url: str = Field(default="https://www.begambleaware.org")

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, v: str) -> str:
        # Hosted Postgres (Render, Heroku, ...) hands out postgres:// or postgresql:// URLs,
        # which SQLAlchemy maps to psycopg2; this app ships psycopg 3.
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()

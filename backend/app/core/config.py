"""Environment-based configuration. Secrets come only from the environment."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    api_football_key: SecretStr | None = None
    thesportsdb_api_key: str = "123"  # free test key; crests only
    provider_timeout_seconds: float = 20.0
    provider_max_retries: int = 3

    # Gemini AI analysis (optional). Several keys may be given, separated by commas;
    # requests rotate through them and skip keys that are rate-limited or rejected.
    gemini_api_keys: SecretStr | None = None
    # Tried in order; a model the API reports as unavailable (404) falls through to the next.
    gemini_models: str = "gemini-3.8-flash,gemini-2.5-flash"
    gemini_search_grounding: bool = True  # let Gemini search the web for team news
    gemini_timeout_seconds: float = 120.0
    # Scheduled analysis for fixtures kicking off within this many hours (0 disables it)
    gemini_auto_hours: int = 48
    gemini_auto_max_per_run: int = 10
    gemini_refresh_hours: float = 12.0  # re-analyse when the latest analysis is older than this

    @property
    def gemini_key_list(self) -> list[str]:
        raw = self.gemini_api_keys.get_secret_value() if self.gemini_api_keys else ""
        return list(dict.fromkeys(k.strip() for k in raw.replace("\n", ",").split(",") if k.strip()))

    @property
    def gemini_model_list(self) -> list[str]:
        return [m.strip() for m in self.gemini_models.split(",") if m.strip()]

    # Competitions to track, by internal code (see app/ingestion/competitions.py)
    competitions: list[str] = ["ENG-1", "ENG-2", "GER-1", "ESP-1", "ITA-1", "FRA-1"]
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

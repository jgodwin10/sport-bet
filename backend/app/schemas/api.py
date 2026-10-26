"""Request/response contracts for the v1 API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class ErrorResponse(BaseModel):
    detail: str


# ------------------------------------------------------------------- auth
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    role: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    role: str


# --------------------------------------------------------------- fixtures
class TeamRef(BaseModel):
    id: int
    name: str
    logo_url: str | None = None


class CompetitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    country: str
    tier: int | None


class PredictionBrief(BaseModel):
    id: int
    created_at: datetime
    classification: str
    one_x_two: dict[str, float]
    reliability_score: float
    reliability_label: str
    lineup_status: str
    best_selection: dict[str, Any] | None
    odds_age_hours: float | None


class FixtureOut(BaseModel):
    id: int
    competition: CompetitionOut
    season: str
    home_team: TeamRef
    away_team: TeamRef
    kickoff_utc: datetime
    status: str
    neutral: bool
    venue: str | None
    score: dict[str, int | None] | None
    latest_prediction: PredictionBrief | None


class FixtureAnalysis(BaseModel):
    fixture: FixtureOut
    prediction: dict[str, Any] | None
    prediction_history: list[dict[str, Any]]
    form: dict[str, Any]
    head_to_head: list[dict[str, Any]]
    standings_context: dict[str, Any]
    availability: list[dict[str, Any]]
    lineups: list[dict[str, Any]]
    odds: dict[str, Any]
    data_quality: dict[str, Any]
    sources: list[dict[str, Any]]
    disclaimer: str


# ----------------------------------------------------------- predictions
class SelectionRow(BaseModel):
    selection_id: int
    prediction_id: int
    fixture_id: int
    match: str
    home_team: TeamRef
    away_team: TeamRef
    competition: str
    kickoff_utc: datetime
    market: str
    selection: str
    probability: float
    probability_lower: float | None
    odds: float
    bookmaker: str | None
    implied_probability: float
    fair_probability: float | None
    edge: float
    expected_value: float
    qualifies: bool
    rejection_reasons: list[str]
    reliability_score: float
    reliability_label: str
    odds_age_hours: float | None
    predicted_at: datetime
    status: Literal["upcoming", "settled", "awaiting_result"]
    outcome: str | None
    profit: float | None
    clv: float | None


# ---------------------------------------------------------------- backtest
class BacktestRequest(BaseModel):
    competitions: list[str] = Field(min_length=1, max_length=20)
    date_from: date
    date_to: date
    step_days: int = Field(default=7, ge=1, le=31)
    price_source: Literal["best", "avg"] = "best"
    rules: dict[str, float | bool] = Field(default_factory=dict)
    deploy: bool = False

    @model_validator(mode="after")
    def _check_dates(self) -> BacktestRequest:
        if self.date_to <= self.date_from:
            raise ValueError("date_to must be after date_from")
        return self


class BacktestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    finished_at: datetime | None
    status: str
    params: dict[str, Any]
    metrics: dict[str, Any] | None
    error: str | None


class ModelVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    version: str
    status: str
    created_at: datetime
    trained_from: date | None
    trained_to: date | None
    feature_definitions: list[Any]
    ensemble_weights: dict[str, Any]
    validated_markets: list[Any]
    metrics: dict[str, Any]
    backtest_id: int | None


# ---------------------------------------------------------------- settings
class RulesIn(BaseModel):
    min_probability: float | None = Field(default=None, ge=0, le=1)
    min_edge: float | None = Field(default=None, ge=-1, le=1)
    min_ev: float | None = Field(default=None, ge=-1, le=5)
    min_odds: float | None = Field(default=None, ge=1.01, le=100)
    max_odds: float | None = Field(default=None, ge=1.01, le=1000)
    min_reliability: float | None = Field(default=None, ge=0, le=100)
    max_odds_age_hours: float | None = Field(default=None, ge=0, le=168)
    require_lower_bound_ev_positive: bool | None = None
    max_disagreement: float | None = Field(default=None, ge=0, le=1)


class OptionsIn(BaseModel):
    preferred_competitions: list[str] | None = None
    enabled_markets: list[Literal["1x2", "totals_1.5", "totals_2.5", "totals_3.5", "asian_handicap"]] | None = None
    timezone: str | None = Field(default=None, max_length=64)
    notifications_enabled: bool | None = None
    stake_tracking_enabled: bool | None = None
    max_stake_per_selection: float | None = Field(default=None, gt=0, le=1_000_000)
    max_daily_stake: float | None = Field(default=None, gt=0, le=1_000_000)


class SettingsUpdate(BaseModel):
    rules: RulesIn | None = None
    options: OptionsIn | None = None


class StakeIn(BaseModel):
    selection_id: int
    stake: float = Field(gt=0, le=1_000_000)


class IngestRequest(BaseModel):
    kind: Literal["history", "upcoming", "odds", "predict", "settle", "logos", "ai_analysis"]
    competitions: list[str] | None = None
    seasons: int | None = Field(default=None, ge=1, le=15)

"""Normalised relational schema.

Conventions:
* All timestamps are timezone-aware UTC.
* Internal integer IDs are provider-independent; provider IDs live in
  `provider_mappings` / `team_aliases`.
* Facts that change over time (odds, lineups, availability, predictions) are
  append-only snapshots so any historical prediction can be reproduced.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Float, LargeBinary, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

JSONType = JSON().with_variant(JSONB(), "postgresql")


class UTCDateTime(TypeDecorator):
    """Always returns timezone-aware UTC datetimes (SQLite drops tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("naive datetimes are not allowed; use UTC-aware values")
            value = value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)  # PostgreSQL returns the session timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    type_annotation_map = {datetime: UTCDateTime(), dict[str, Any]: JSONType, list[Any]: JSONType}


# ------------------------------------------------------------------ identity
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="viewer")  # viewer | admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AppSetting(Base):
    """Server-side, admin-editable settings (never secrets)."""

    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(255))


# -------------------------------------------------------------- provenance
class SourceRecord(Base):
    """One retrieval from one provider. Every ingested fact points at one of these."""

    __tablename__ = "source_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)
    resource: Mapped[str] = mapped_column(String(255))
    retrieved_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    trust_level: Mapped[int] = mapped_column(Integer, default=50)  # 0-100, provider/source specific
    verification: Mapped[str] = mapped_column(String(20), default="confirmed")  # confirmed|projected|inferred|unavailable
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)


class DataConflict(Base):
    __tablename__ = "data_conflicts"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(Integer, index=True)
    field: Mapped[str] = mapped_column(String(100))
    values: Mapped[list[Any]] = mapped_column()  # [{source_record_id, provider, value, retrieved_at, trust}]
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    material: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ProviderMapping(Base):
    __tablename__ = "provider_mappings"
    __table_args__ = (UniqueConstraint("provider", "entity_type", "provider_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(50))
    entity_type: Mapped[str] = mapped_column(String(30))  # competition|fixture|player|team
    provider_id: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[int] = mapped_column(Integer, index=True)


# ------------------------------------------------------------ competitions
class Competition(Base):
    __tablename__ = "competitions"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # e.g. ENG-1
    name: Mapped[str] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(60))
    tier: Mapped[int | None] = mapped_column(Integer)
    format: Mapped[str] = mapped_column(String(20), default="league")  # league|cup
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Season(Base):
    __tablename__ = "seasons"
    __table_args__ = (UniqueConstraint("competition_id", "label"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"))
    label: Mapped[str] = mapped_column(String(20))  # 2026-2027
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    country: Mapped[str | None] = mapped_column(String(60))
    logo_url: Mapped[str | None] = mapped_column(String(500))
    logo_source: Mapped[str | None] = mapped_column(String(50))
    logo_checked_at: Mapped[datetime | None] = mapped_column()
    aliases: Mapped[list[TeamAlias]] = relationship(back_populates="team")


class TeamCrest(Base):
    """Cached crest image bytes so browsers load crests from our origin, fast, with no third-party requests."""

    __tablename__ = "team_crests"
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), primary_key=True)
    size: Mapped[str] = mapped_column(String(10), primary_key=True)  # tiny (100px) | small (200px)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    content_type: Mapped[str] = mapped_column(String(50))
    source_url: Mapped[str] = mapped_column(String(500))
    fetched_at: Mapped[datetime] = mapped_column(default=utcnow)


class TeamAlias(Base):
    __tablename__ = "team_aliases"
    __table_args__ = (UniqueConstraint("provider", "alias"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    provider: Mapped[str] = mapped_column(String(50))
    alias: Mapped[str] = mapped_column(String(120))
    normalized: Mapped[str] = mapped_column(String(120), index=True)
    provider_team_id: Mapped[str | None] = mapped_column(String(60))
    team: Mapped[Team] = relationship(back_populates="aliases")


class Player(Base):
    __tablename__ = "players"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), index=True)
    position: Mapped[str | None] = mapped_column(String(30))


# ---------------------------------------------------------------- fixtures
FIXTURE_STATUSES = ("scheduled", "live", "finished", "postponed", "abandoned", "cancelled")


class Fixture(Base):
    __tablename__ = "fixtures"
    __table_args__ = (Index("ix_fixtures_kickoff_status", "kickoff_utc", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    natural_key: Mapped[str] = mapped_column(String(200), unique=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"), index=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), index=True)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    kickoff_utc: Mapped[datetime] = mapped_column()
    kickoff_source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"))
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    venue: Mapped[str | None] = mapped_column(String(120))
    neutral: Mapped[bool] = mapped_column(Boolean, default=False)
    stage: Mapped[str] = mapped_column(String(30), default="league")  # league|cup|playoff
    leg: Mapped[int | None] = mapped_column(Integer)
    referee: Mapped[str | None] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    competition: Mapped[Competition] = relationship()
    season: Mapped[Season] = relationship()
    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id])
    result: Mapped[MatchResult | None] = relationship(back_populates="fixture", uselist=False)


class MatchResult(Base):
    __tablename__ = "match_results"
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), primary_key=True)
    home_goals: Mapped[int] = mapped_column(Integer)
    away_goals: Mapped[int] = mapped_column(Integer)
    ht_home_goals: Mapped[int | None] = mapped_column(Integer)
    ht_away_goals: Mapped[int | None] = mapped_column(Integer)
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"))
    recorded_at: Mapped[datetime] = mapped_column(default=utcnow)
    fixture: Mapped[Fixture] = relationship(back_populates="result")


class TeamMatchStats(Base):
    __tablename__ = "team_match_stats"
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), primary_key=True)
    is_home: Mapped[bool] = mapped_column(Boolean)
    shots: Mapped[int | None] = mapped_column(Integer)
    shots_on_target: Mapped[int | None] = mapped_column(Integer)
    xg: Mapped[float | None] = mapped_column(Float)
    corners: Mapped[int | None] = mapped_column(Integer)
    fouls: Mapped[int | None] = mapped_column(Integer)
    yellow_cards: Mapped[int | None] = mapped_column(Integer)
    red_cards: Mapped[int | None] = mapped_column(Integer)
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"))


class PlayerMatchStats(Base):
    __tablename__ = "player_match_stats"
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True)
    minutes: Mapped[int | None] = mapped_column(Integer)
    started: Mapped[bool | None] = mapped_column(Boolean)
    goals: Mapped[int | None] = mapped_column(Integer)
    assists: Mapped[int | None] = mapped_column(Integer)
    source_record_id: Mapped[int | None] = mapped_column(ForeignKey("source_records.id"))


class Lineup(Base):
    """Append-only lineup snapshots; status distinguishes projected vs confirmed."""

    __tablename__ = "lineups"
    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    status: Mapped[str] = mapped_column(String(20))  # projected | confirmed
    formation: Mapped[str | None] = mapped_column(String(20))
    players: Mapped[list[Any]] = mapped_column(default=list)  # [{name, position, number, starter}]
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_records.id"))
    retrieved_at: Mapped[datetime] = mapped_column(default=utcnow)


class AvailabilityReport(Base):
    """Injuries, suspensions and doubts. Never inferred: each row cites its source."""

    __tablename__ = "availability_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int | None] = mapped_column(ForeignKey("fixtures.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    player_name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))  # injury | suspension | doubtful | other
    reason: Mapped[str | None] = mapped_column(String(255))
    verification: Mapped[str] = mapped_column(String(20))  # confirmed | reported | unverified
    expected_return: Mapped[date | None] = mapped_column(Date)
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_records.id"))
    retrieved_at: Mapped[datetime] = mapped_column(default=utcnow)


class NewsReport(Base):
    __tablename__ = "news_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), index=True)
    fixture_id: Mapped[int | None] = mapped_column(ForeignKey("fixtures.id"), index=True)
    headline: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(30))  # manager|squad|discipline|motivation|other
    verification: Mapped[str] = mapped_column(String(20))
    published_at: Mapped[datetime | None] = mapped_column()
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_records.id"))


# -------------------------------------------------------------------- odds
class Bookmaker(Base):
    __tablename__ = "bookmakers"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))


class OddsSnapshot(Base):
    """One price for one selection at one point in time. Never updated in place."""

    __tablename__ = "odds_snapshots"
    __table_args__ = (
        Index("ix_odds_fixture_market_time", "fixture_id", "market", "retrieved_at"),
        UniqueConstraint("fixture_id", "bookmaker_id", "market", "line", "selection", "kind", "observed_at",
                         name="uq_odds_observation"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"))
    bookmaker_id: Mapped[int] = mapped_column(ForeignKey("bookmakers.id"))
    market: Mapped[str] = mapped_column(String(30))  # 1x2 | totals | asian_handicap | btts
    line: Mapped[float] = mapped_column(Float, default=0.0)  # 0 when not applicable
    selection: Mapped[str] = mapped_column(String(20))  # home|draw|away|over|under|yes|no
    decimal_odds: Mapped[float] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(20))  # pre_match | closing
    observed_at: Mapped[datetime] = mapped_column()  # when the price was valid (provider timestamp)
    retrieved_at: Mapped[datetime] = mapped_column(default=utcnow)
    source_record_id: Mapped[int] = mapped_column(ForeignKey("source_records.id"))
    bookmaker: Mapped[Bookmaker] = relationship()


# ------------------------------------------------------------------ models
class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("name", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="candidate")  # candidate|deployed|retired
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    trained_from: Mapped[date | None] = mapped_column(Date)
    trained_to: Mapped[date | None] = mapped_column(Date)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    feature_definitions: Mapped[list[Any]] = mapped_column(default=list)
    ensemble_weights: Mapped[dict[str, Any]] = mapped_column(default=dict)
    validated_markets: Mapped[list[Any]] = mapped_column(default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)
    backtest_id: Mapped[int | None] = mapped_column(ForeignKey("backtests.id"))


class ModelFeatureSnapshot(Base):
    __tablename__ = "model_features"
    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), index=True)
    computed_at: Mapped[datetime] = mapped_column(default=utcnow)
    as_of: Mapped[datetime] = mapped_column()  # information cutoff
    features: Mapped[dict[str, Any]] = mapped_column()


class Prediction(Base):
    """Immutable prediction snapshot. Updates create a new row that `supersedes` the old one."""

    __tablename__ = "predictions"
    __table_args__ = (Index("ix_predictions_fixture_created", "fixture_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"))
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"))
    feature_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("model_features.id"))
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("predictions.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    information_cutoff: Mapped[datetime] = mapped_column()
    trigger: Mapped[str] = mapped_column(String(30))  # initial|odds_refresh|lineup|news|manual
    lineup_status: Mapped[str] = mapped_column(String(20))  # unavailable|projected|confirmed
    markets: Mapped[dict[str, Any]] = mapped_column()  # final probabilities per market
    components: Mapped[dict[str, Any]] = mapped_column()  # per-model 1X2 + weights
    intervals: Mapped[dict[str, Any] | None] = mapped_column()
    reliability: Mapped[dict[str, Any]] = mapped_column()
    classification: Mapped[str] = mapped_column(String(20))  # consider|no_bet|high_uncertainty
    data_quality: Mapped[dict[str, Any]] = mapped_column()  # sources, freshness, gaps, conflicts
    inputs_hash: Mapped[str] = mapped_column(String(64))
    change_summary: Mapped[list[Any] | None] = mapped_column()

    fixture: Mapped[Fixture] = relationship()
    explanations: Mapped[list[PredictionExplanation]] = relationship(order_by="PredictionExplanation.position")
    selections: Mapped[list[Selection]] = relationship()


class PredictionExplanation(Base):
    __tablename__ = "prediction_explanations"
    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column()  # feature names/values the text was built from


class Selection(Base):
    """A priced candidate selection evaluated against the rules (qualifying or not)."""

    __tablename__ = "selections"
    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"), index=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), index=True)
    market: Mapped[str] = mapped_column(String(30))
    selection: Mapped[str] = mapped_column(String(20))
    line: Mapped[float] = mapped_column(Float, default=0.0)
    probability: Mapped[float] = mapped_column(Float)
    probability_lower: Mapped[float | None] = mapped_column(Float)
    decimal_odds: Mapped[float] = mapped_column(Float)
    bookmaker: Mapped[str | None] = mapped_column(String(50))
    implied_probability: Mapped[float] = mapped_column(Float)
    fair_probability: Mapped[float | None] = mapped_column(Float)  # margin-removed market probability
    edge: Mapped[float] = mapped_column(Float)
    expected_value: Mapped[float] = mapped_column(Float)
    qualifies: Mapped[bool] = mapped_column(Boolean, index=True)
    rejection_reasons: Mapped[list[Any]] = mapped_column(default=list)
    settlement: Mapped[SettledSelection | None] = relationship(uselist=False)


class SettledSelection(Base):
    __tablename__ = "settled_selections"
    selection_id: Mapped[int] = mapped_column(ForeignKey("selections.id"), primary_key=True)
    outcome: Mapped[str] = mapped_column(String(20))  # win|loss|push|half_win|half_loss|void
    profit: Mapped[float] = mapped_column(Float)  # per unit stake
    closing_odds: Mapped[float | None] = mapped_column(Float)
    clv: Mapped[float | None] = mapped_column(Float)  # taken odds / closing odds - 1
    settled_at: Mapped[datetime] = mapped_column(default=utcnow)


class StakeEntry(Base):
    """Optional user stake tracking. Purely a record; nothing is ever placed."""

    __tablename__ = "stake_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    selection_id: Mapped[int] = mapped_column(ForeignKey("selections.id"))
    stake: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AiAnalysis(Base):
    """Narrative match analysis written by an LLM (OpenAI or Gemini) from the model output plus web search.

    Advisory only: it never feeds probabilities, selections or reliability. Rows are kept
    (including failures) so AI views can later be compared against results.
    """

    __tablename__ = "ai_analyses"
    __table_args__ = (Index("ix_ai_analyses_fixture_created", "fixture_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"))
    prediction_id: Mapped[int | None] = mapped_column(ForeignKey("predictions.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    status: Mapped[str] = mapped_column(String(20))  # ok | failed
    provider: Mapped[str] = mapped_column(String(30), default="gemini")
    model: Mapped[str | None] = mapped_column(String(60))
    key_slot: Mapped[int | None] = mapped_column(Integer)  # which configured key served it (never the key)
    trigger: Mapped[str] = mapped_column(String(30))  # manual | scheduled
    requested_by: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[dict[str, Any] | None] = mapped_column()
    sources: Mapped[list[Any]] = mapped_column(default=list)  # [{title, uri}] from search grounding
    search_queries: Mapped[list[Any]] = mapped_column(default=list)
    error: Mapped[str | None] = mapped_column(Text)


class TopPickEntry(Base):
    """A match that appeared in the Top 10, for tracking the list's results.

    Updated on every recording until kickoff, then frozen: it keeps the selection (and so the
    odds) from the last time the match was listed. `in_list` says whether the match was still
    in the Top 10 at the last recording before kickoff; only those count towards P&L.
    """

    __tablename__ = "top_pick_entries"
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), primary_key=True)
    selection_id: Mapped[int] = mapped_column(ForeignKey("selections.id"))
    rank: Mapped[int] = mapped_column(Integer)  # rank at the last listing
    best_rank: Mapped[int] = mapped_column(Integer)
    tier: Mapped[str] = mapped_column(String(20))  # recommended|watchlist at the last listing
    in_list: Mapped[bool] = mapped_column(Boolean)
    first_listed_at: Mapped[datetime] = mapped_column()
    last_listed_at: Mapped[datetime] = mapped_column()
    recorded_at: Mapped[datetime] = mapped_column()  # last recording that saw this fixture before kickoff

    selection: Mapped[Selection] = relationship()


class DailySlip(Base):
    """One day's 2 odds accumulator and the analysis behind it.

    Refreshed until the first leg kicks off, then frozen. `legs` holds the selection and the
    checks for each leg: [{selection_id, fixture_id, checks}]. A day with no qualifying
    combination keeps a row with no legs, so its record shows the day was passed on.
    """

    __tablename__ = "daily_slips"
    slip_date: Mapped[date] = mapped_column(Date, primary_key=True)
    legs: Mapped[list[Any]] = mapped_column(default=list)
    combined_odds: Mapped[float | None] = mapped_column(Float)
    combined_probability: Mapped[float | None] = mapped_column(Float)
    analysed: Mapped[int] = mapped_column(Integer, default=0)  # favourites given the full analysis
    spare: Mapped[int] = mapped_column(Integer, default=0)  # passed every check but not needed
    rejected: Mapped[list[Any]] = mapped_column(default=list)  # [{match, selection, probability, reasons, ...}]
    changes: Mapped[list[Any]] = mapped_column(default=list)  # [{at, reason}] when published legs were replaced
    first_built_at: Mapped[datetime] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column()


# --------------------------------------------------------------- backtests
class Backtest(Base):
    __tablename__ = "backtests"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|completed|failed
    params: Mapped[dict[str, Any]] = mapped_column()
    metrics: Mapped[dict[str, Any] | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[str | None] = mapped_column(String(255))


# ------------------------------------------------------------- operations
class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(50), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|succeeded|failed
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column()
    stats: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(100))
    entity: Mapped[str | None] = mapped_column(String(100))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class ImmutableRecordError(RuntimeError):
    pass


@event.listens_for(Session, "before_flush")
def _protect_immutable(session: Session, *_: object) -> None:
    """Predictions, their explanations/selections and odds snapshots are append-only."""
    for obj in session.dirty:
        if isinstance(obj, (Prediction, PredictionExplanation, Selection, OddsSnapshot)) and session.is_modified(obj):
            raise ImmutableRecordError(f"{type(obj).__name__} rows are immutable")
    for obj in session.deleted:
        if isinstance(obj, (Prediction, PredictionExplanation)):
            raise ImmutableRecordError(f"{type(obj).__name__} rows cannot be deleted")

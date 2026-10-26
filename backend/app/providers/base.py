"""Provider-independent data types and the adapter contract.

Adapters translate a provider's payloads into these normalised types and never
fill gaps: a field the provider does not supply stays None.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol


@dataclass(frozen=True)
class NormalizedOdds:
    bookmaker_key: str
    bookmaker_name: str
    market: str  # 1x2 | totals | asian_handicap | btts
    selection: str  # home|draw|away|over|under|yes|no
    decimal_odds: float
    kind: str  # pre_match | closing
    observed_at: datetime
    line: float = 0.0


@dataclass
class TeamStats:
    shots: int | None = None
    shots_on_target: int | None = None
    xg: float | None = None
    corners: int | None = None
    fouls: int | None = None
    yellow_cards: int | None = None
    red_cards: int | None = None


@dataclass
class NormalizedFixture:
    provider: str
    provider_fixture_id: str | None
    competition_code: str
    season_label: str
    home_name: str
    away_name: str
    kickoff_utc: datetime
    status: str  # scheduled|live|finished|postponed|abandoned|cancelled
    neutral: bool = False
    kickoff_approximate: bool = False
    stage: str = "league"
    venue: str | None = None
    referee: str | None = None
    home_goals: int | None = None
    away_goals: int | None = None
    ht_home_goals: int | None = None
    ht_away_goals: int | None = None
    home_stats: TeamStats | None = None
    away_stats: TeamStats | None = None
    odds: list[NormalizedOdds] = field(default_factory=list)


@dataclass
class NormalizedAvailability:
    team_name: str
    player_name: str
    kind: str  # injury | suspension | doubtful | other
    verification: str  # confirmed | reported | unverified
    reason: str | None = None
    expected_return: date | None = None
    provider_fixture_id: str | None = None


@dataclass
class NormalizedLineup:
    team_name: str
    status: str  # projected | confirmed
    formation: str | None
    players: list[dict[str, object]]  # {name, number, position, starter}


@dataclass
class ProviderBatch:
    """Result of one adapter call plus the provenance needed to store it."""

    provider: str
    resource: str
    retrieved_at: datetime
    payload_hash: str
    trust_level: int
    fixtures: list[NormalizedFixture] = field(default_factory=list)
    availability: list[NormalizedAvailability] = field(default_factory=list)
    lineups: list[NormalizedLineup] = field(default_factory=list)
    meta: dict[str, object] = field(default_factory=dict)


class ProviderNotConfigured(RuntimeError):
    """Raised when an adapter is used without the credentials it needs."""


class ProviderError(RuntimeError):
    pass


class Provider(Protocol):
    name: str
    trust_level: int

    @property
    def configured(self) -> bool: ...

    def capabilities(self) -> dict[str, object]: ...

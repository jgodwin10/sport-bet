"""Persist normalised provider batches with provenance and conflict handling.

Conflict rules (kickoff, status, result):
1. Original values are preserved in `data_conflicts` together with their source.
2. Higher trust wins; at equal trust the more recent retrieval wins.
3. When trust levels are close (< 10 apart) and values differ materially, the
   conflict stays *unresolved* and downstream reliability is reduced.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.db.models import (
    AvailabilityReport, Bookmaker, Competition, DataConflict, Fixture, Lineup, MatchResult, OddsSnapshot,
    ProviderMapping, Season, SourceRecord, TeamMatchStats,
)
from app.ingestion.competitions import COMPETITIONS
from app.ingestion.teams import TeamResolver
from app.providers.base import NormalizedFixture, ProviderBatch, TeamStats

log = logging.getLogger(__name__)

# Fixture-creating providers. Others (odds-only) are matched to existing fixtures.
FIXTURE_SOURCES = {"football_data_co_uk", "football_data_org", "api_football"}


@dataclass
class StoreStats:
    fixtures_created: int = 0
    fixtures_updated: int = 0
    results: int = 0
    odds: int = 0
    unmatched: list[str] = field(default_factory=list)
    conflicts: int = 0
    skipped_duplicate_payload: bool = False

    def as_dict(self) -> dict[str, object]:
        return {**self.__dict__, "unmatched": self.unmatched[:50]}


class Store:
    def __init__(self, db: Session, odds_bookmakers: set[str] | None = None) -> None:
        self.db = db
        self.teams = TeamResolver(db)
        self.odds_bookmakers = odds_bookmakers  # restrict which bookmakers are stored (None = all)
        self._bookmakers: dict[str, int] = {}
        self._seasons: dict[tuple[int, str], int] = {}

    # ------------------------------------------------------------- reference
    def competition(self, code: str) -> Competition:
        comp = self.db.scalar(select(Competition).where(Competition.code == code))
        if comp is None:
            d = COMPETITIONS[code]
            comp = Competition(code=code, name=d.name, country=d.country, tier=d.tier)
            self.db.add(comp)
            self.db.flush()
        return comp

    def season_id(self, competition_id: int, label: str) -> int:
        key = (competition_id, label)
        if key not in self._seasons:
            season = self.db.scalar(select(Season).where(Season.competition_id == competition_id,
                                                         Season.label == label))
            if season is None:
                season = Season(competition_id=competition_id, label=label)
                self.db.add(season)
                self.db.flush()
            self._seasons[key] = season.id
        return self._seasons[key]

    def bookmaker_id(self, key: str, name: str) -> int:
        if key not in self._bookmakers:
            bk = self.db.scalar(select(Bookmaker).where(Bookmaker.key == key))
            if bk is None:
                bk = Bookmaker(key=key, name=name)
                self.db.add(bk)
                self.db.flush()
            self._bookmakers[key] = bk.id
        return self._bookmakers[key]

    # ------------------------------------------------------------ provenance
    def source(self, batch: ProviderBatch, verification: str = "confirmed") -> tuple[SourceRecord, bool]:
        """Return the source record and whether this exact payload was already ingested."""
        existing = self.db.scalar(select(SourceRecord).where(
            SourceRecord.provider == batch.provider, SourceRecord.resource == batch.resource,
            SourceRecord.payload_hash == batch.payload_hash).limit(1))
        if existing:
            return existing, True
        rec = SourceRecord(provider=batch.provider, resource=batch.resource, retrieved_at=batch.retrieved_at,
                           payload_hash=batch.payload_hash, trust_level=batch.trust_level,
                           verification=verification, meta=batch.meta)
        self.db.add(rec)
        self.db.flush()
        return rec, False

    # --------------------------------------------------------------- fixtures
    def ingest_fixtures(self, batch: ProviderBatch, force: bool = False) -> StoreStats:
        stats = StoreStats()
        src, duplicate = self.source(batch)
        if duplicate and not force:
            stats.skipped_duplicate_payload = True
            return stats
        for nf in batch.fixtures:
            fixture = self._match_or_create(nf, src, stats)
            if fixture is None:
                continue
            if nf.provider_fixture_id:
                self._map(nf.provider, "fixture", nf.provider_fixture_id, fixture.id)
            if nf.home_goals is not None and nf.away_goals is not None:
                self._result(fixture, nf, src, stats)
            if nf.home_stats or nf.away_stats:
                self._team_stats(fixture, nf.home_stats, fixture.home_team_id, True, src)
                self._team_stats(fixture, nf.away_stats, fixture.away_team_id, False, src)
            if nf.odds:
                stats.odds += self._odds(fixture, nf, src)
        self.db.flush()
        return stats

    def _match_or_create(self, nf: NormalizedFixture, src: SourceRecord, stats: StoreStats) -> Fixture | None:
        comp = self.competition(nf.competition_code)
        create = nf.provider in FIXTURE_SOURCES
        home = self.teams.resolve(nf.provider, nf.home_name, nf.competition_code, can_create=create)
        away = self.teams.resolve(nf.provider, nf.away_name, nf.competition_code, can_create=create)
        if home is None or away is None:
            stats.unmatched.append(f"{nf.competition_code}: {nf.home_name} v {nf.away_name}")
            return None
        season_id = self.season_id(comp.id, nf.season_label)
        natural_key = (f"{comp.code}:{nf.season_label}:{home}:{away}" if nf.stage == "league"
                       else f"{comp.code}:{nf.season_label}:{home}:{away}:{nf.kickoff_utc.date()}")

        fixture = None
        if nf.provider_fixture_id:
            mapped = self.db.scalar(select(ProviderMapping.entity_id).where(
                ProviderMapping.provider == nf.provider, ProviderMapping.entity_type == "fixture",
                ProviderMapping.provider_id == nf.provider_fixture_id))
            fixture = self.db.get(Fixture, mapped) if mapped else None
        if fixture is None:
            fixture = self.db.scalar(select(Fixture).where(Fixture.natural_key == natural_key))
        if fixture is None and nf.provider not in FIXTURE_SOURCES:
            window = timedelta(days=3)
            fixture = self.db.scalar(select(Fixture).where(
                Fixture.home_team_id == home, Fixture.away_team_id == away,
                Fixture.kickoff_utc.between(nf.kickoff_utc - window, nf.kickoff_utc + window)))
        if fixture is None:
            if nf.provider not in FIXTURE_SOURCES:
                stats.unmatched.append(f"{nf.competition_code}: {nf.home_name} v {nf.away_name} (no fixture)")
                return None
            fixture = Fixture(natural_key=natural_key, competition_id=comp.id, season_id=season_id,
                              home_team_id=home, away_team_id=away, kickoff_utc=nf.kickoff_utc,
                              kickoff_source_record_id=src.id, status=nf.status, neutral=nf.neutral,
                              stage=nf.stage, venue=nf.venue, referee=nf.referee)
            self.db.add(fixture)
            self.db.flush()
            stats.fixtures_created += 1
            return fixture

        if nf.provider in FIXTURE_SOURCES:
            changed = self._resolve_kickoff(fixture, nf, src)
            if nf.status != fixture.status and self._status_allowed(fixture, nf, src):
                fixture.status = nf.status
                changed = True
            for attr in ("venue", "referee"):
                if getattr(nf, attr) and not getattr(fixture, attr):
                    setattr(fixture, attr, getattr(nf, attr))
            stats.fixtures_updated += int(changed)
        return fixture

    def _trust_of(self, source_record_id: int | None) -> tuple[int, datetime | None]:
        if source_record_id is None:
            return 0, None
        rec = self.db.get(SourceRecord, source_record_id)
        return (rec.trust_level, rec.retrieved_at) if rec else (0, None)

    def _resolve_kickoff(self, fixture: Fixture, nf: NormalizedFixture, src: SourceRecord) -> bool:
        if abs((fixture.kickoff_utc - nf.kickoff_utc).total_seconds()) < 60:
            return False
        old_trust, _ = self._trust_of(fixture.kickoff_source_record_id)
        # A new value is accepted from a source at least as trusted (the newer
        # retrieval wins ties) unless the incoming time is a placeholder.
        accept = src.trust_level >= old_trust and not nf.kickoff_approximate
        close_trust = abs(src.trust_level - old_trust) < 10 and src.provider != self._provider_of(
            fixture.kickoff_source_record_id)
        self.db.add(DataConflict(
            entity_type="fixture", entity_id=fixture.id, field="kickoff_utc",
            values=[
                {"source_record_id": fixture.kickoff_source_record_id, "value": fixture.kickoff_utc.isoformat(),
                 "trust": old_trust},
                {"source_record_id": src.id, "provider": src.provider, "value": nf.kickoff_utc.isoformat(),
                 "trust": src.trust_level},
            ],
            resolved=not close_trust,
            material=abs((fixture.kickoff_utc - nf.kickoff_utc).total_seconds()) > 3600,
            resolution=("accepted newer value from equally/more trusted source" if accept
                        else "kept value from more trusted source") + ("; flagged: trust levels close"
                                                                       if close_trust else ""),
        ))
        if accept:
            fixture.kickoff_utc = nf.kickoff_utc
            fixture.kickoff_source_record_id = src.id
        return accept

    def _provider_of(self, source_record_id: int | None) -> str | None:
        rec = self.db.get(SourceRecord, source_record_id) if source_record_id else None
        return rec.provider if rec else None

    def _status_allowed(self, fixture: Fixture, nf: NormalizedFixture, src: SourceRecord) -> bool:
        # Results files only know "finished"; a scheduled entry from a lower-trust
        # weekly file must not revert a postponement reported by a trusted API.
        if fixture.status in ("postponed", "cancelled", "abandoned") and nf.status == "scheduled":
            old_trust, _ = self._trust_of(fixture.kickoff_source_record_id)
            return src.trust_level > old_trust
        return not (fixture.status == "finished" and nf.status != "finished")

    def _result(self, fixture: Fixture, nf: NormalizedFixture, src: SourceRecord, stats: StoreStats) -> None:
        existing = self.db.get(MatchResult, fixture.id)
        if existing is None:
            self.db.add(MatchResult(fixture_id=fixture.id, home_goals=nf.home_goals, away_goals=nf.away_goals,
                                    ht_home_goals=nf.ht_home_goals, ht_away_goals=nf.ht_away_goals,
                                    source_record_id=src.id))
            fixture.status = "finished"
            stats.results += 1
        elif (existing.home_goals, existing.away_goals) != (nf.home_goals, nf.away_goals):
            self.db.add(DataConflict(
                entity_type="match_result", entity_id=fixture.id, field="score", material=True,
                values=[{"source_record_id": existing.source_record_id,
                         "value": [existing.home_goals, existing.away_goals]},
                        {"source_record_id": src.id, "provider": src.provider,
                         "value": [nf.home_goals, nf.away_goals]}],
                resolution="unresolved: providers disagree on final score; settlement withheld",
            ))
            stats.conflicts += 1

    def _team_stats(self, fixture: Fixture, ts: TeamStats | None, team_id: int, is_home: bool,
                    src: SourceRecord) -> None:
        if ts is None:
            return
        row = self.db.get(TeamMatchStats, (fixture.id, team_id))
        if row is None:
            row = TeamMatchStats(fixture_id=fixture.id, team_id=team_id, is_home=is_home)
            self.db.add(row)
        for attr, value in ts.__dict__.items():
            if value is not None:
                setattr(row, attr, value)
        row.source_record_id = src.id

    def _odds(self, fixture: Fixture, nf: NormalizedFixture, src: SourceRecord) -> int:
        rows = []
        for o in nf.odds:
            if self.odds_bookmakers is not None and o.bookmaker_key not in self.odds_bookmakers:
                continue
            if o.kind == "pre_match" and o.observed_at > fixture.kickoff_utc:
                continue  # a "pre-match" price observed after kickoff is not pre-match
            rows.append({
                "fixture_id": fixture.id, "bookmaker_id": self.bookmaker_id(o.bookmaker_key, o.bookmaker_name),
                "market": o.market, "line": o.line, "selection": o.selection, "decimal_odds": o.decimal_odds,
                "kind": o.kind, "observed_at": o.observed_at, "retrieved_at": src.retrieved_at,
                "source_record_id": src.id,
            })
        if not rows:
            return 0
        dialect = self.db.get_bind().dialect.name
        insert = postgresql.insert if dialect == "postgresql" else sqlite.insert
        self.db.execute(insert(OddsSnapshot).values(rows).on_conflict_do_nothing())
        return len(rows)

    def _map(self, provider: str, entity_type: str, provider_id: str, entity_id: int) -> None:
        exists = self.db.scalar(select(ProviderMapping.id).where(
            ProviderMapping.provider == provider, ProviderMapping.entity_type == entity_type,
            ProviderMapping.provider_id == provider_id))
        if not exists:
            self.db.add(ProviderMapping(provider=provider, entity_type=entity_type, provider_id=provider_id,
                                        entity_id=entity_id))

    # ----------------------------------------------------------- team news
    def ingest_availability(self, batch: ProviderBatch, fixture: Fixture) -> int:
        src, duplicate = self.source(batch, verification="reported")
        if duplicate:
            return 0
        comp_code = fixture.competition.code
        n = 0
        for a in batch.availability:
            team_id = self.teams.resolve(batch.provider, a.team_name, comp_code)
            if team_id not in (fixture.home_team_id, fixture.away_team_id):
                continue
            self.db.add(AvailabilityReport(fixture_id=fixture.id, team_id=team_id, player_name=a.player_name,
                                           kind=a.kind, reason=a.reason, verification=a.verification,
                                           expected_return=a.expected_return, source_record_id=src.id,
                                           retrieved_at=batch.retrieved_at))
            n += 1
        return n

    def ingest_lineups(self, batch: ProviderBatch, fixture: Fixture) -> int:
        src, duplicate = self.source(batch, verification="confirmed")
        if duplicate:
            return 0
        n = 0
        for lu in batch.lineups:
            team_id = self.teams.resolve(batch.provider, lu.team_name, fixture.competition.code)
            if team_id not in (fixture.home_team_id, fixture.away_team_id):
                continue
            self.db.add(Lineup(fixture_id=fixture.id, team_id=team_id, status=lu.status, formation=lu.formation,
                               players=lu.players, source_record_id=src.id, retrieved_at=batch.retrieved_at))
            n += 1
        return n

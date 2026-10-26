"""Ingestion use-cases. Each run is recorded in `ingestion_jobs` under an
idempotency key so retried or duplicated tasks do not double-process."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Fixture, IngestionJob, ProviderMapping
from app.ingestion.competitions import COMPETITIONS
from app.ingestion.store import Store
from app.providers.base import ProviderError, ProviderNotConfigured
from app.providers.football_data_co_uk import current_season_start
from app.providers.registry import Providers

log = logging.getLogger(__name__)

HISTORY_BOOKMAKERS = {"avg", "max", "ps", "b365", "bfe"}


class JobAlreadyRan(RuntimeError):
    pass


def run_job(db: Session, job_type: str, key: str, params: dict, fn: Callable[[], dict]) -> IngestionJob:
    """Execute `fn` once per idempotency key; failed jobs may be retried."""
    job = db.scalar(select(IngestionJob).where(IngestionJob.idempotency_key == key))
    if job and job.status in ("succeeded", "running"):
        if job.status == "running" and job.started_at < datetime.now(timezone.utc) - timedelta(hours=2):
            log.warning("job %s was stuck in running; retrying", key)
        else:
            return job
    if job is None:
        job = IngestionJob(job_type=job_type, idempotency_key=key, params=params, status="running")
        db.add(job)
        try:
            db.commit()
        except IntegrityError:  # another worker created it concurrently
            db.rollback()
            return db.scalar(select(IngestionJob).where(IngestionJob.idempotency_key == key))
    else:
        job.status, job.attempts, job.error = "running", job.attempts + 1, None
        job.started_at = datetime.now(timezone.utc)
        db.commit()
    try:
        job.stats = fn()
        job.status = "succeeded"
    except Exception as exc:  # noqa: BLE001 - recorded and re-raised for the task's retry policy
        db.rollback()
        job = db.get(IngestionJob, job.id)
        job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    return job


class IngestionService:
    def __init__(self, db: Session, providers: Providers, settings: Settings) -> None:
        self.db = db
        self.providers = providers
        self.settings = settings

    def history(self, competitions: list[str] | None = None, seasons: int | None = None,
                today: date | None = None) -> dict:
        """Load past seasons' results, stats and pre-match/closing odds."""
        today = today or datetime.now(timezone.utc).date()
        competitions = competitions or self.settings.competitions
        seasons = seasons or self.settings.history_seasons
        start = current_season_start(today)
        summary: dict[str, object] = {}
        for code in competitions:
            if not COMPETITIONS[code].fdcuk:
                continue
            for year in range(start - seasons + 1, start + 1):
                store = Store(self.db, odds_bookmakers=HISTORY_BOOKMAKERS)
                try:
                    batch = self.providers.fdcuk.season(code, year)
                except ProviderError as exc:
                    summary[f"{code}:{year}"] = {"error": str(exc)}
                    continue
                stats = store.ingest_fixtures(batch)
                self.db.commit()
                summary[f"{code}:{year}"] = stats.as_dict()
        return summary

    def upcoming(self, days_ahead: int = 10) -> dict:
        """Upcoming fixtures: weekly file (keyless) plus authoritative schedule APIs when configured."""
        summary: dict[str, object] = {}
        wanted = set(self.settings.competitions)
        if self.providers.fdcuk.configured:
            try:
                batch = self.providers.fdcuk.upcoming()
                batch.fixtures = [f for f in batch.fixtures if f.competition_code in wanted]
                summary["football_data_co_uk"] = Store(self.db).ingest_fixtures(batch).as_dict()
                self.db.commit()
            except ProviderError as exc:
                summary["football_data_co_uk"] = {"error": str(exc)}
        today = datetime.now(timezone.utc).date()
        for code in wanted:
            for label, call in (
                ("football_data_org", lambda c=code: self.providers.fdorg.matches(c, today - timedelta(days=3),
                                                                                    today + timedelta(days=days_ahead))),
                ("api_football", lambda c=code: self.providers.api_football.fixtures(c, today,
                                                                                    today + timedelta(days=days_ahead))),
            ):
                try:
                    batch = call()
                except ProviderNotConfigured:
                    continue
                except (ProviderError, ValueError) as exc:
                    summary[f"{label}:{code}"] = {"error": str(exc)}
                    continue
                summary[f"{label}:{code}"] = Store(self.db).ingest_fixtures(batch).as_dict()
                self.db.commit()
        return summary

    def odds(self) -> dict:
        summary: dict[str, object] = {}
        if not self.providers.odds_api.configured:
            return {"the_odds_api": "not configured; using odds from football-data.co.uk weekly file"}
        for code in self.settings.competitions:
            try:
                batch = self.providers.odds_api.odds(code)
            except (ProviderError, ValueError) as exc:
                summary[code] = {"error": str(exc)}
                continue
            summary[code] = Store(self.db).ingest_fixtures(batch).as_dict()
            self.db.commit()
        return summary

    def team_news(self, fixture: Fixture) -> dict:
        """Injuries and lineups for one fixture (requires API-Football)."""
        provider = self.providers.api_football
        if not provider.configured:
            return {"api_football": "not configured"}
        pid = self.db.scalar(select(ProviderMapping.provider_id).where(
            ProviderMapping.provider == provider.name, ProviderMapping.entity_type == "fixture",
            ProviderMapping.entity_id == fixture.id))
        if not pid:
            return {"api_football": "fixture not mapped to provider id"}
        store = Store(self.db)
        out = {"availability": store.ingest_availability(provider.injuries(pid), fixture)}
        if fixture.kickoff_utc - datetime.now(timezone.utc) <= timedelta(minutes=self.settings.lineup_window_minutes):
            out["lineups"] = store.ingest_lineups(provider.lineups(pid), fixture)
        self.db.commit()
        return out

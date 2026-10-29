"""Ingestion use-cases. Each run is recorded in `ingestion_jobs` under an
idempotency key so retried or duplicated tasks do not double-process."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Competition, Fixture, IngestionJob, OddsSnapshot, ProviderMapping, Season, SourceRecord
from app.engine.elo import season_of
from app.ingestion.competitions import COMPETITIONS
from app.ingestion.store import Store
from app.providers.base import ProviderError, ProviderNotConfigured
from app.providers.football_data_co_uk import current_season_start
from app.providers.registry import Providers
from app.services.top_picks import top_picks

log = logging.getLogger(__name__)

HISTORY_BOOKMAKERS = {"avg", "max", "ps", "b365", "bfe"}


def _days_left_in_month(now: datetime) -> int:
    first_next = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
    return max(1, (first_next.date() - now.date()).days)


def _credits(meta: dict, default: int | None) -> int | None:
    try:
        return int(meta["requests_remaining"])
    except (KeyError, TypeError, ValueError):
        return default


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
            if COMPETITIONS[code].format == "cup":
                summary.update(self._cup_history(code, range(start - seasons + 1, start + 1), start))
                continue
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

    def _cup_history(self, code: str, years: range, current: int) -> dict:
        """Cup seasons from API-Football, one request each. A finished season is fetched once:
        the free plan allows 100 requests a day and only some seasons."""
        summary: dict[str, object] = {}
        for year in years:
            if year < current and self._has_results(code, season_of(date(year, 9, 1))):
                continue
            try:
                batch = self.providers.api_football.season(code, year)
            except ProviderNotConfigured:
                return {code: "API_FOOTBALL_KEY not set: no cup history"}
            except (ProviderError, ValueError) as exc:
                summary[f"{code}:{year}"] = {"error": str(exc)}
                continue
            summary[f"{code}:{year}"] = Store(self.db).ingest_fixtures(batch).as_dict()
            self.db.commit()
        return summary

    def _has_results(self, code: str, season_label: str) -> bool:
        return self.db.scalar(
            select(Fixture.id).join(Season, Season.id == Fixture.season_id)
            .join(Competition, Competition.id == Fixture.competition_id)
            .where(Competition.code == code, Season.label == season_label, Fixture.status == "finished")
            .limit(1)) is not None

    def _awaiting_result(self, code: str, now: datetime) -> bool:
        """A fixture in this competition kicked off 2h-3d ago and still has no result."""
        return self.db.scalar(
            select(Fixture.id).join(Competition, Competition.id == Fixture.competition_id)
            .where(Competition.code == code, Fixture.status == "scheduled",
                   Fixture.kickoff_utc.between(now - timedelta(days=3), now - timedelta(hours=2)))
            .limit(1)) is not None

    def _upcoming_in(self, code: str, now: datetime, days: int, unpriced: bool = False) -> bool:
        """A scheduled fixture kicks off in the next `days` days (and, if `unpriced`, has no odds yet)."""
        q = (select(Fixture.id).join(Competition, Competition.id == Fixture.competition_id)
             .where(Competition.code == code, Fixture.status == "scheduled",
                    Fixture.kickoff_utc.between(now, now + timedelta(days=days))))
        if unpriced:
            q = q.where(~exists().where(OddsSnapshot.fixture_id == Fixture.id, OddsSnapshot.kind == "pre_match"))
        return self.db.scalar(q.limit(1)) is not None

    def _cups(self, wanted: set[str], now: datetime) -> dict:
        """Cup fixtures from The Odds API's free event list, and recent cup results (2 credits a
        call) when a finished tie is still missing one and football-data.org doesn't cover it."""
        summary: dict[str, object] = {}
        odds_api, fdorg = self.providers.odds_api, self.providers.fdorg
        if not odds_api.configured:
            return summary
        for code in sorted(c for c in wanted if COMPETITIONS[c].format == "cup" and COMPETITIONS[c].odds_api):
            calls = [("events", odds_api.events)]
            if self._awaiting_result(code, now) and not (COMPETITIONS[code].fdorg and fdorg.configured):
                calls.append(("scores", odds_api.scores))
            for label, call in calls:
                try:
                    batch = call(code)
                except (ProviderError, ValueError) as exc:
                    summary[f"the_odds_api:{label}:{code}"] = {"error": str(exc)}
                    continue
                summary[f"the_odds_api:{label}:{code}"] = Store(self.db).ingest_fixtures(batch).as_dict()
                self.db.commit()
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
        summary.update(self._cups(wanted, datetime.now(timezone.utc)))
        for code in wanted:
            for label, call in (
                ("football_data_org", lambda c=code: self.providers.fdorg.matches(c, today - timedelta(days=3),
                                                                                    today + timedelta(days=days_ahead))),
                ("api_football", lambda c=code: self.providers.api_football.fixtures(c, today,
                                                                                    today + timedelta(days=days_ahead))),
            ):
                try:
                    batch = call()
                except (ProviderNotConfigured, ValueError):
                    continue  # no key, or the provider doesn't cover this competition
                except ProviderError as exc:
                    summary[f"{label}:{code}"] = {"error": str(exc)}
                    continue
                summary[f"{label}:{code}"] = Store(self.db).ingest_fixtures(batch).as_dict()
                self.db.commit()
        return summary

    def odds(self) -> dict:
        summary: dict[str, object] = {}
        if not self.providers.odds_api.configured:
            return {"the_odds_api": "not configured; using odds from football-data.co.uk weekly file"}
        s = self.settings
        now = datetime.now(timezone.utc)
        priced = set(s.odds_api_competitions)
        remaining = self._credits_remaining(now - timedelta(hours=24))
        matchday = self._matchday_competitions(now)
        # Match-day re-pricing is optional: it stops early enough to leave a daily allowance for
        # routine pricing until the credits renew (taken as the start of next month).
        paced = s.odds_api_credit_reserve + s.odds_api_daily_allowance * _days_left_in_month(now)
        for code in s.competitions:
            if code not in priced or not COMPETITIONS[code].odds_api:
                continue
            if COMPETITIONS[code].format == "cup":
                due = self._upcoming_in(code, now, s.odds_api_days_ahead)
                why = f"no fixture in the next {s.odds_api_days_ahead} days"
            else:
                due = self._upcoming_in(code, now, s.odds_api_days_ahead, unpriced=True)
                why = f"every fixture in the next {s.odds_api_days_ahead} days has odds"
            if due and self._priced_since(code, now - timedelta(hours=s.odds_api_refresh_hours)):
                due, why = False, f"priced in the last {s.odds_api_refresh_hours:g}h"
            floor = s.odds_api_credit_reserve
            if not due and code in matchday and not self._priced_since(
                    code, now - timedelta(hours=s.odds_api_matchday_refresh_hours)):
                due, floor = True, paced
            if not due:
                summary[code] = f"skipped: {why}"
                continue
            if remaining is not None and remaining < floor:
                summary[code] = f"skipped: {remaining} credits left (reserve {floor})"
                continue
            try:
                batch = self.providers.odds_api.odds(code)
            except (ProviderError, ValueError) as exc:
                summary[code] = {"error": str(exc)}
                continue
            remaining = _credits(batch.meta, remaining)
            summary[code] = Store(self.db).ingest_fixtures(batch).as_dict()
            self.db.commit()
        if remaining is not None:
            summary["credits_remaining"] = remaining
        return summary

    def _credits_remaining(self, since: datetime) -> int | None:
        """Credits left as of the latest Odds API response stored after `since` (None if unknown)."""
        meta = self.db.scalar(
            select(SourceRecord.meta).where(SourceRecord.provider == self.providers.odds_api.name,
                                            SourceRecord.retrieved_at > since)
            .order_by(SourceRecord.retrieved_at.desc(), SourceRecord.id.desc()).limit(1))
        return _credits(meta or {}, None)

    def _matchday_competitions(self, now: datetime) -> set[str]:
        """Competitions with a top pick kicking off within the match-day window whose latest odds are
        older than the match-day refresh interval: the "odds missing or stale" rule would hold it back."""
        s = self.settings
        soon = now + timedelta(hours=s.odds_api_matchday_hours)
        stale = now - timedelta(hours=s.odds_api_matchday_refresh_hours)
        out = set()
        for t in top_picks(self.db, now):
            if t.fixture.kickoff_utc > soon or t.competition in out:
                continue
            observed = self.db.scalar(select(func.max(OddsSnapshot.observed_at)).where(
                OddsSnapshot.fixture_id == t.fixture.id, OddsSnapshot.kind == "pre_match"))
            if observed is not None and observed < stale:
                out.add(t.competition)
        return out

    def _priced_since(self, code: str, since: datetime) -> bool:
        """The Odds API priced this competition after `since` (a priced call is a /odds resource)."""
        return self.db.scalar(
            select(SourceRecord.id).where(
                SourceRecord.provider == self.providers.odds_api.name,
                SourceRecord.resource == f"/sports/{COMPETITIONS[code].odds_api}/odds",
                SourceRecord.retrieved_at > since)
            .limit(1)) is not None

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

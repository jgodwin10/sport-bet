"""Job bodies shared by Celery tasks, the CLI and inline (no-worker) mode.

Each job opens its own DB session and records itself in `ingestion_jobs` under a
time-bucketed idempotency key, so a duplicated or retried trigger inside the
same bucket does not repeat the work.
"""

from __future__ import annotations

import logging
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.core.config import get_settings
from app.db.models import Fixture
from app.db.session import get_engine, session_factory
from app.ingestion.logos import refresh_logos
from app.ingestion.service import IngestionService, run_job
from app.providers.registry import get_providers
from app.services.ai_analysis import AiAnalysisService
from app.services.backtests import execute_backtest
from app.services.prediction import PredictionService
from app.services.settlement import settle_finished
from app.services.top_picks import record_top_picks

log = logging.getLogger(__name__)


def _bucket(minutes: int) -> str:
    now = datetime.now(timezone.utc)
    return f"{now:%Y%m%d}-{(now.hour * 60 + now.minute) // max(minutes, 1)}"


# History, upcoming and odds all write through ingestion.store, which inserts shared rows
# (seasons, teams, fixtures) inside long per-batch transactions. Two overlapping runs would
# block on each other's uncommitted inserts until the statement timeout.
INGEST_LOCK = "ingest"
SKIPPED = {"skipped": "another ingestion job is running"}


@contextmanager
def exclusive(name: str) -> Iterator[bool]:
    """Postgres advisory lock shared by the API, the CLI and scheduled runs; yields False
    instead of waiting when another process holds it. Held on its own connection because
    an ORM session may switch connections between transactions. No-op on SQLite."""
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        yield True
        return
    key = zlib.crc32(name.encode())
    with engine.connect() as conn:
        acquired = bool(conn.execute(text("select pg_try_advisory_lock(:k)"), {"k": key}).scalar())
        conn.commit()
        try:
            yield acquired
        finally:
            if acquired:
                conn.execute(text("select pg_advisory_unlock(:k)"), {"k": key})
                conn.commit()


def ingest_history(competitions: list[str] | None = None, seasons: int | None = None, force: bool = False) -> dict:
    s = get_settings()
    with exclusive(INGEST_LOCK) as acquired, session_factory()() as db:
        if not acquired:
            return SKIPPED
        comps = competitions or s.competitions
        # The key column holds 200 chars and the competition list can be long, so it is hashed;
        # params keep the readable list.
        key = f"history:{zlib.crc32(','.join(comps).encode()):08x}:{seasons or s.history_seasons}:" + (
            datetime.now(timezone.utc).isoformat() if force else _bucket(24 * 60))
        job = run_job(db, "history", key, {"competitions": comps, "seasons": seasons or s.history_seasons},
                      lambda: IngestionService(db, get_providers(), s).history(competitions, seasons))
        return {"job_id": job.id, "status": job.status, "stats": job.stats}


def ingest_logos(force: bool = False) -> dict:
    with session_factory()() as db:
        key = f"logos:{datetime.now(timezone.utc).isoformat() if force else _bucket(24 * 60)}"
        job = run_job(db, "logos", key, {"force": force}, lambda: refresh_logos(db, get_providers().crests, force=force))
        return {"job_id": job.id, "status": job.status, "stats": job.stats}


def ingest_upcoming() -> dict:
    s = get_settings()
    with exclusive(INGEST_LOCK) as acquired, session_factory()() as db:
        if not acquired:
            return SKIPPED
        job = run_job(db, "upcoming", f"upcoming:{_bucket(s.fixtures_refresh_minutes)}", {},
                      lambda: IngestionService(db, get_providers(), s).upcoming())
        return {"job_id": job.id, "status": job.status, "stats": job.stats}


def refresh_odds() -> dict:
    s = get_settings()
    with exclusive(INGEST_LOCK) as acquired, session_factory()() as db:
        if not acquired:
            return SKIPPED
        job = run_job(db, "odds", f"odds:{_bucket(s.odds_refresh_minutes)}", {},
                      lambda: IngestionService(db, get_providers(), s).odds())
        return {"job_id": job.id, "status": job.status, "stats": job.stats}


def refresh_team_news() -> dict:
    """Injuries for fixtures in the next 48h; lineups inside the lineup window."""
    s = get_settings()
    now = datetime.now(timezone.utc)
    out: dict[str, object] = {}
    with session_factory()() as db:
        fixtures = list(db.scalars(select(Fixture).where(
            Fixture.status == "scheduled", Fixture.kickoff_utc > now, Fixture.kickoff_utc < now + timedelta(hours=48))))
        changed = []
        svc = IngestionService(db, get_providers(), s)
        for f in fixtures:
            try:
                res = svc.team_news(f)
            except Exception as exc:  # noqa: BLE001 - provider outage must not block other fixtures
                db.rollback()
                out[str(f.id)] = {"error": str(exc)}
                continue
            out[str(f.id)] = res
            if res.get("availability") or res.get("lineups"):
                changed.append(f.id)
        if changed:
            out["predictions"] = PredictionService(db, s).predict_upcoming("team_news", fixture_ids=changed)
    return out


def run_predictions(trigger: str = "scheduled", fixture_ids: list[int] | None = None) -> dict:
    with session_factory()() as db:
        out = PredictionService(db, get_settings()).predict_upcoming(trigger, fixture_ids=fixture_ids)
        try:
            out["top_picks"] = record_top_picks(db, datetime.now(timezone.utc))
        except Exception:  # noqa: BLE001 - tracking must not fail the predictions themselves
            db.rollback()
            log.exception("recording the top picks failed")
            out["top_picks"] = "failed"
        return out


def ai_analysis(fixture_ids: list[int] | None = None) -> dict:
    """AI analysis for upcoming fixtures (or the given ones) whose analysis is missing or stale."""
    with session_factory()() as db:
        svc = AiAnalysisService(db, get_settings())
        if not fixture_ids:
            return svc.analyse_upcoming()
        out: dict[str, object] = {}
        for fid in fixture_ids:
            f = db.get(Fixture, fid)
            try:
                row = svc.analyse(f, trigger="manual", requested_by="cli") if f else None
                out[str(fid)] = row.status if row else "fixture not found"
            except Exception as exc:  # noqa: BLE001 - report per fixture
                db.rollback()
                out[str(fid)] = {"error": str(exc)}
        return out


def settle() -> dict:
    with session_factory()() as db:
        return settle_finished(db)


def run_backtest(backtest_id: int) -> dict:
    with session_factory()() as db:
        bt = execute_backtest(db, backtest_id, get_settings())
        return {"backtest_id": bt.id, "status": bt.status}


def refresh_fixture(fixture_id: int) -> dict:
    s = get_settings()
    with session_factory()() as db:
        f = db.get(Fixture, fixture_id)
        if f is None:
            return {"error": "fixture not found"}
        svc = IngestionService(db, get_providers(), s)
        out: dict[str, object] = {}
        for name, fn in (("odds", svc.odds), ("team_news", lambda: svc.team_news(f))):
            try:
                out[name] = fn()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                out[name] = {"error": str(exc)}
        out["prediction"] = PredictionService(db, s).predict_upcoming("manual", fixture_ids=[fixture_id])
        return out


def update_cycle() -> dict:
    """Fixtures -> odds -> predictions -> settlement. Each step tolerates failure of the others."""
    out: dict[str, object] = {}
    for name, fn in (("upcoming", ingest_upcoming), ("odds", refresh_odds), ("settle", settle),
                     ("predictions", lambda: run_predictions("scheduled"))):
        try:
            out[name] = fn()
        except Exception as exc:  # noqa: BLE001
            log.exception("update cycle step %s failed", name)
            out[name] = {"error": str(exc)}
    return out


JOBS = {
    "ingest_history": ingest_history, "ingest_logos": ingest_logos, "ingest_upcoming": ingest_upcoming, "refresh_odds": refresh_odds,
    "refresh_team_news": refresh_team_news, "run_predictions": run_predictions, "ai_analysis": ai_analysis, "settle": settle,
    "run_backtest": run_backtest, "refresh_fixture": refresh_fixture, "update_cycle": update_cycle,
}

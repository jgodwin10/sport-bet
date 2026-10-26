"""Celery worker and beat schedule. Start with:
    celery -A app.worker.celery_app worker -l info
    celery -A app.worker.celery_app beat -l info
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.providers.base import ProviderError
from app.worker import jobs

settings = get_settings()
configure_logging(settings.log_level)

celery = Celery("footy", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=60 * 60,
    timezone="UTC",
    result_expires=24 * 3600,
    beat_schedule={
        "update-cycle": {"task": "footy.update_cycle", "schedule": settings.odds_refresh_minutes * 60},
        "team-news": {"task": "footy.refresh_team_news", "schedule": settings.lineup_check_minutes * 60},
        "history-daily": {"task": "footy.ingest_history", "schedule": 24 * 3600},
        "crests-daily": {"task": "footy.ingest_logos", "schedule": 24 * 3600},
        "ai-analysis": {"task": "footy.ai_analysis", "schedule": settings.odds_refresh_minutes * 60},
    },
)

RETRY = {"autoretry_for": (ProviderError,), "retry_backoff": 30, "retry_backoff_max": 600, "max_retries": 4}


def _single_flight(name: str, ttl: int):
    """Redis lock so overlapping beat ticks do not run the same job concurrently."""
    import redis

    client = redis.Redis.from_url(settings.redis_url)
    return client.lock(f"lock:{name}", timeout=ttl, blocking=False)


def _register(name: str, fn, ttl: int = 3600, **opts):
    @celery.task(name=f"footy.{name}", **opts)
    def _task(*args, **kwargs):
        lock = _single_flight(name, ttl)
        if not lock.acquire(blocking=False):
            return {"skipped": "already running"}
        try:
            return fn(*args, **kwargs)
        finally:
            try:
                lock.release()
            except Exception:  # noqa: BLE001 - lock may have expired
                pass

    return _task


ingest_history = _register("ingest_history", jobs.ingest_history, ttl=3 * 3600, **RETRY)
ingest_logos = _register("ingest_logos", jobs.ingest_logos, ttl=2 * 3600)
ingest_upcoming = _register("ingest_upcoming", jobs.ingest_upcoming, **RETRY)
refresh_odds = _register("refresh_odds", jobs.refresh_odds, **RETRY)
refresh_team_news = _register("refresh_team_news", jobs.refresh_team_news, ttl=900)
run_predictions = _register("run_predictions", jobs.run_predictions)
settle = _register("settle", jobs.settle)
ai_analysis = _register("ai_analysis", jobs.ai_analysis, ttl=3600)
update_cycle = _register("update_cycle", jobs.update_cycle)
refresh_fixture = celery.task(name="footy.refresh_fixture")(jobs.refresh_fixture)
run_backtest = celery.task(name="footy.run_backtest")(jobs.run_backtest)

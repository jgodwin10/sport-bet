"""Dispatch background jobs to Celery, or run them in a thread when TASK_MODE=inline
(local development without a worker)."""

from __future__ import annotations

import logging
import threading

from app.core.config import get_settings
from app.worker.jobs import JOBS

log = logging.getLogger(__name__)


def dispatch(name: str, *args, **kwargs) -> dict:
    if get_settings().task_mode == "celery":
        from app.worker.celery_app import celery

        result = celery.send_task(f"footy.{name}", args=args, kwargs=kwargs)
        return {"mode": "celery", "task_id": result.id}

    def run() -> None:
        try:
            JOBS[name](*args, **kwargs)
        except Exception:  # noqa: BLE001
            log.exception("inline job %s failed", name)

    threading.Thread(target=run, name=f"job-{name}", daemon=True).start()
    return {"mode": "inline", "task_id": None}

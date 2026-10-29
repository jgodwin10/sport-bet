"""Health, auth, settings, data quality, backtests and admin operations."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_token, require_admin, require_user, verify_password
from app.db.models import (
    AuditLog, Backtest, Competition, DataConflict, Fixture, IngestionJob, MatchResult, ModelVersion, Selection,
    StakeEntry, User,
)
from app.db.session import get_db
from app.ingestion.competitions import COMPETITIONS
from app.providers.ai import get_ai
from app.providers.registry import get_providers
from app.schemas.api import (
    BacktestOut, BacktestRequest, CompetitionOut, IngestRequest, LoginRequest, ModelVersionOut, Page,
    SettingsUpdate, StakeIn, TokenResponse, UserOut,
)
from app.services.backtests import deploy_version
from app.services.settings_store import get_app_options, get_rules, set_app_options, set_rules
from app.worker.dispatch import dispatch

router = APIRouter()


def audit(db: Session, actor: str, action: str, entity: str | None = None, details: dict | None = None) -> None:
    db.add(AuditLog(actor=actor, action=action, entity=entity, details=details or {}))
    db.commit()


# ------------------------------------------------------------------ system
@router.get("/system/health", tags=["system"])
def health(db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    checks: dict[str, object] = {}
    try:
        db.execute(text("select 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {type(exc).__name__}"
    try:
        import redis

        redis.Redis.from_url(s.redis_url, socket_connect_timeout=0.5).ping()
        checks["redis"] = "ok"
    except Exception:  # noqa: BLE001
        checks["redis"] = "unavailable" + (" (required in celery mode)" if s.task_mode == "celery" else "")
    jobs = db.scalars(select(IngestionJob).order_by(IngestionJob.started_at.desc()).limit(10))
    last_result = db.scalar(select(func.max(MatchResult.recorded_at)))
    return {
        "status": "ok" if checks["database"] == "ok" else "degraded", "checks": checks,
        "task_mode": s.task_mode, "environment": s.environment,
        "providers": [{k: v for k, v in p.items() if k != "capabilities"} for p in get_providers().status()],
        "ai": get_ai().status(),
        "recent_jobs": [{"id": j.id, "type": j.job_type, "status": j.status, "started_at": j.started_at,
                         "finished_at": j.finished_at, "error": j.error} for j in jobs],
        "last_result_recorded_at": last_result,
        "server_time": datetime.now(timezone.utc),
    }


@router.get("/system/providers", tags=["system"])
def providers() -> list[dict]:
    return get_providers().status()


@router.get("/competitions", response_model=list[CompetitionOut], tags=["system"])
def competitions(db: Session = Depends(get_db)) -> list[Competition]:
    return list(db.scalars(select(Competition).order_by(Competition.country, Competition.tier)))


@router.get("/data-quality", tags=["system"])
def data_quality(db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    conflicts = db.scalars(select(DataConflict).where(DataConflict.resolved.is_(False))
                           .order_by(DataConflict.created_at.desc()).limit(100))
    missing_results = db.execute(
        select(Fixture.id, Fixture.kickoff_utc).where(Fixture.status == "scheduled",
                                                      Fixture.kickoff_utc < now - timedelta(hours=6))
        .order_by(Fixture.kickoff_utc.desc()).limit(50)).all()
    return {
        "unresolved_conflicts": [{"id": c.id, "entity_type": c.entity_type, "entity_id": c.entity_id,
                                  "field": c.field, "values": c.values, "material": c.material,
                                  "resolution": c.resolution, "created_at": c.created_at} for c in conflicts],
        "fixtures_missing_results": [{"fixture_id": i, "kickoff_utc": k} for i, k in missing_results],
    }


# -------------------------------------------------------------------- auth
@router.post("/auth/login", response_model=TokenResponse, tags=["auth"])
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "invalid credentials")
    return TokenResponse(access_token=create_token(user), role=user.role)


@router.get("/auth/me", response_model=UserOut, tags=["auth"])
def me(user: User = Depends(require_user)) -> User:
    return user


# ---------------------------------------------------------------- settings
@router.get("/settings", tags=["settings"])
def read_settings(db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    return {
        "rules": asdict(get_rules(db)), "options": get_app_options(db),
        "server": {  # read-only, non-secret server configuration
            "tracked_competitions": s.competitions,
            "available_competitions": [{"code": c.code, "name": c.name, "country": c.country}
                                       for c in COMPETITIONS.values()],
            "update_intervals_minutes": {"fixtures": s.fixtures_refresh_minutes, "odds": s.odds_refresh_minutes,
                                         "lineups": s.lineup_check_minutes},
            "providers": [{k: v for k, v in p.items()} for p in get_providers().status()],
            "ai": get_ai().status(),
            "responsible_gambling_url": s.responsible_gambling_url,
        },
    }


@router.put("/settings", tags=["settings"])
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    if body.rules:
        values = body.rules.model_dump(exclude_none=True)
        set_rules(db, values, admin.email)
        audit(db, admin.email, "settings.rules", None, values)
    if body.options:
        values = body.options.model_dump(exclude_none=True)
        set_app_options(db, values, admin.email)
        audit(db, admin.email, "settings.options", None, values)
    return read_settings(db)


# ------------------------------------------------------------------ stakes
@router.post("/stakes", tags=["stakes"])
def record_stake(body: StakeIn, db: Session = Depends(get_db), user: User = Depends(require_user)) -> dict:
    """Optional personal record-keeping with hard limits. Nothing is placed with any bookmaker."""
    opts = get_app_options(db)
    if not opts["stake_tracking_enabled"]:
        raise HTTPException(400, "stake tracking is disabled in settings")
    if db.get(Selection, body.selection_id) is None:
        raise HTTPException(404, "selection not found")
    if body.stake > opts["max_stake_per_selection"]:
        raise HTTPException(400, f"stake exceeds the configured per-selection limit ({opts['max_stake_per_selection']})")
    since = datetime.now(timezone.utc) - timedelta(days=1)
    today = db.scalar(select(func.coalesce(func.sum(StakeEntry.stake), 0.0)).where(
        StakeEntry.user_id == user.id, StakeEntry.created_at >= since)) or 0.0
    if today + body.stake > opts["max_daily_stake"]:
        raise HTTPException(400, f"stake would exceed the configured 24h limit ({opts['max_daily_stake']})")
    entry = StakeEntry(user_id=user.id, selection_id=body.selection_id, stake=body.stake)
    db.add(entry)
    db.commit()
    return {"id": entry.id, "stake": entry.stake, "remaining_24h": opts["max_daily_stake"] - today - body.stake}


@router.get("/stakes", tags=["stakes"])
def list_stakes(db: Session = Depends(get_db), user: User = Depends(require_user)) -> list[dict]:
    rows = db.scalars(select(StakeEntry).where(StakeEntry.user_id == user.id).order_by(StakeEntry.created_at.desc()))
    return [{"id": r.id, "selection_id": r.selection_id, "stake": r.stake, "created_at": r.created_at} for r in rows]


# --------------------------------------------------------------- backtests
@router.post("/backtests", response_model=BacktestOut, status_code=202, tags=["backtests"])
def create_backtest(body: BacktestRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> Backtest:
    unknown = set(body.competitions) - set(COMPETITIONS)
    if unknown:
        raise HTTPException(422, f"unknown competitions: {sorted(unknown)}")
    bt = Backtest(params=body.model_dump(mode="json"), status="queued", requested_by=admin.email)
    db.add(bt)
    db.commit()
    audit(db, admin.email, "backtest.create", f"backtest:{bt.id}", body.model_dump(mode="json"))
    dispatch("run_backtest", bt.id)
    return bt


@router.get("/backtests", response_model=Page[BacktestOut], tags=["backtests"])
def list_backtests(db: Session = Depends(get_db), page: int = Query(1, ge=1),
                   page_size: int = Query(20, ge=1, le=100)) -> Page[BacktestOut]:
    total = db.scalar(select(func.count(Backtest.id))) or 0
    rows = db.scalars(select(Backtest).order_by(Backtest.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    items = []
    for b in rows:
        out = BacktestOut.model_validate(b)
        if out.metrics:  # list view: drop the heavy per-bet arrays
            out.metrics = {k: v for k, v in out.metrics.items() if k not in ("bets", "calibration", "weights_history")}
        items.append(out)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/backtests/{backtest_id}", response_model=BacktestOut, tags=["backtests"])
def get_backtest(backtest_id: int, db: Session = Depends(get_db)) -> Backtest:
    bt = db.get(Backtest, backtest_id)
    if bt is None:
        raise HTTPException(404, "backtest not found")
    return bt


# ------------------------------------------------------------------- admin
@router.post("/admin/refresh-fixture/{fixture_id}", status_code=202, tags=["admin"])
def refresh_fixture(fixture_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    if db.get(Fixture, fixture_id) is None:
        raise HTTPException(404, "fixture not found")
    audit(db, admin.email, "fixture.refresh", f"fixture:{fixture_id}")
    return dispatch("refresh_fixture", fixture_id)


@router.post("/admin/ingest", status_code=202, tags=["admin"])
def ingest(body: IngestRequest, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> dict:
    audit(db, admin.email, f"ingest.{body.kind}", None, body.model_dump())
    match body.kind:
        case "history":
            return dispatch("ingest_history", body.competitions, body.seasons, True)
        case "upcoming":
            return dispatch("ingest_upcoming")
        case "odds":
            return dispatch("refresh_odds")
        case "predict":
            return dispatch("run_predictions", "manual")
        case "logos":
            return dispatch("ingest_logos", True)
        case "ai_analysis":
            return dispatch("ai_analysis")
        case _:
            return dispatch("settle")


@router.get("/admin/jobs", tags=["admin"])
def jobs(db: Session = Depends(get_db), _: User = Depends(require_admin), limit: int = Query(50, le=200)) -> list[dict]:
    rows = db.scalars(select(IngestionJob).order_by(IngestionJob.started_at.desc()).limit(limit))
    return [{"id": j.id, "type": j.job_type, "key": j.idempotency_key, "status": j.status, "attempts": j.attempts,
             "started_at": j.started_at, "finished_at": j.finished_at, "stats": j.stats, "error": j.error}
            for j in rows]


@router.post("/admin/models/{model_id}/deploy", response_model=ModelVersionOut, tags=["admin"])
def deploy(model_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)) -> ModelVersion:
    m = db.get(ModelVersion, model_id)
    if m is None:
        raise HTTPException(404, "model version not found")
    deploy_version(db, m)
    db.commit()
    audit(db, admin.email, "model.deploy", f"model:{model_id}")
    return m


@router.get("/admin/audit", tags=["admin"])
def audit_log(request: Request, db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[dict]:
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(100))
    return [{"actor": a.actor, "action": a.action, "entity": a.entity, "details": a.details,
             "created_at": a.created_at} for a in rows]

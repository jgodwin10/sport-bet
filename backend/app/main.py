from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.v1 import fixtures, performance, predictions, system, teams
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.security import RateLimiter, client_ip, hash_password
from app.db.models import User
from app.db.session import session_factory

log = logging.getLogger("app")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def bootstrap_admin() -> None:
    s = get_settings()
    if not (s.bootstrap_admin_email and s.bootstrap_admin_password):
        return
    with session_factory()() as db:
        email = s.bootstrap_admin_email.lower()
        if db.scalar(select(User).where(User.email == email)) is None:
            db.add(User(email=email, password_hash=hash_password(s.bootstrap_admin_password.get_secret_value()),
                        role="admin"))
            db.commit()
            log.info("bootstrap admin created")


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        bootstrap_admin()
    except Exception:  # noqa: BLE001 - DB may not be migrated yet; the health endpoint reports it
        log.exception("bootstrap admin failed")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        lifespan=lifespan,
        title="Football Analytics & Prediction API",
        version="1.0.0",
        description="Evidence-based football match probabilities, value assessment and model evaluation. "
                    "Outputs are statistical estimates, not guarantees.",
        docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None,
    )
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT"], allow_headers=["Authorization", "Content-Type"])
    limiter = RateLimiter(settings.rate_limit_per_minute,
                          settings.redis_url if settings.environment != "test" else None)

    @app.middleware("http")
    async def request_pipeline(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        if request.url.path.startswith("/api/v1") and not limiter.hit(client_ip(request)):
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429, headers={"Retry-After": "60"})
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error", extra={"request_id": request_id, "path": request.url.path})
            response = JSONResponse({"detail": "internal server error", "request_id": request_id}, status_code=500)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if settings.is_production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        response.headers["X-Request-ID"] = request_id
        log.info("request", extra={"request_id": request_id, "method": request.method, "path": request.url.path,
                                   "status": response.status_code,
                                   "duration_ms": round((time.perf_counter() - start) * 1000, 1)})
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        return JSONResponse({"detail": "validation error",
                             "errors": [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]}, status_code=422)

    for r in (fixtures.router, predictions.router, performance.router, teams.router, system.router):
        app.include_router(r, prefix="/api/v1")

    return app


app = create_app()

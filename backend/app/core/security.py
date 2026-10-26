from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import User
from app.db.session import get_db

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(user: User) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user.id), "role": user.role, "iat": now,
               "exp": now + timedelta(minutes=s.jwt_ttl_minutes)}
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm="HS256")


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> User | None:
    if creds is None:
        return None
    try:
        payload = jwt.decode(creds.credentials, get_settings().jwt_secret.get_secret_value(), algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token") from None
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "inactive user")
    return user


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin role required")
    return user


class RateLimiter:
    """Fixed-window per-IP limiter. Uses Redis when available so limits are shared
    across API replicas; falls back to process memory otherwise."""

    def __init__(self, per_minute: int, redis_url: str | None) -> None:
        self.per_minute = per_minute
        self._memory: dict[str, tuple[int, int]] = {}
        self._redis = None
        if redis_url:
            try:
                import redis

                client = redis.Redis.from_url(redis_url, socket_connect_timeout=0.3, socket_timeout=0.3)
                client.ping()
                self._redis = client
            except Exception:  # noqa: BLE001 - optional dependency at runtime
                self._redis = None

    def hit(self, key: str) -> bool:
        window = int(time.time() // 60)
        if self._redis is not None:
            try:
                rk = f"rl:{key}:{window}"
                count = self._redis.incr(rk)
                if count == 1:
                    self._redis.expire(rk, 70)
                return count <= self.per_minute
            except Exception:  # noqa: BLE001
                pass
        w, count = self._memory.get(key, (window, 0))
        count = count + 1 if w == window else 1
        self._memory[key] = (window, count)
        return count <= self.per_minute


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"

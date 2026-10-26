"""Shared HTTP client for providers: timeouts, retries with exponential backoff,
per-provider request spacing and an optional response cache."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from app.providers.base import ProviderError

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass
class HttpResult:
    url: str
    status: int
    content: bytes
    headers: dict[str, str]
    retrieved_at: datetime

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    @property
    def last_modified(self) -> datetime | None:
        value = self.headers.get("last-modified")
        if not value:
            return None
        try:
            return parsedate_to_datetime(value).astimezone(timezone.utc)
        except (TypeError, ValueError):
            return None

    def json(self) -> object:
        import json

        return json.loads(self.content)


class _TTLCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, HttpResult]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> HttpResult | None:
        with self._lock:
            item = self._data.get(key)
            if item and item[0] > time.monotonic():
                return item[1]
            self._data.pop(key, None)
            return None

    def set(self, key: str, value: HttpResult, ttl: float) -> None:
        with self._lock:
            self._data[key] = (time.monotonic() + ttl, value)


_cache = _TTLCache()


class ProviderHttpClient:
    def __init__(
        self,
        provider: str,
        timeout: float = 20.0,
        max_retries: int = 3,
        min_interval_seconds: float = 0.0,
        backoff_base: float = 1.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.provider = provider
        self.max_retries = max_retries
        self.min_interval = min_interval_seconds
        self.backoff_base = backoff_base
        self._last_request = 0.0
        self._client = httpx.Client(timeout=timeout, follow_redirects=True, transport=transport,
                                    headers={"User-Agent": "footy-analytics/1.0 (+research use)"})

    def get(
        self, url: str, params: dict[str, object] | None = None, headers: dict[str, str] | None = None,
        cache_ttl: float = 0.0,
    ) -> HttpResult:
        cache_key = f"{url}?{sorted((params or {}).items())}"
        if cache_ttl and (hit := _cache.get(cache_key)):
            return hit
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = self._client.get(url, params=params, headers=headers)
            except httpx.TransportError as exc:
                last_error = exc
                log.warning("provider %s transport error (attempt %d): %s", self.provider, attempt + 1, exc)
            else:
                if resp.status_code < 400:
                    result = HttpResult(str(resp.url), resp.status_code, resp.content,
                                        {k.lower(): v for k, v in resp.headers.items()},
                                        datetime.now(timezone.utc))
                    if cache_ttl:
                        _cache.set(cache_key, result, cache_ttl)
                    return result
                if resp.status_code not in RETRYABLE_STATUS:
                    # Never echo request params: they may contain API keys.
                    raise ProviderError(f"{self.provider} returned HTTP {resp.status_code} for {url}")
                last_error = ProviderError(f"{self.provider} HTTP {resp.status_code}")
                retry_after = resp.headers.get("retry-after")
                if retry_after and retry_after.isdigit():
                    time.sleep(min(int(retry_after), 60))
            if attempt < self.max_retries:
                time.sleep(self.backoff_base * 2**attempt)
        raise ProviderError(f"{self.provider} request failed after {self.max_retries + 1} attempts: {last_error}")

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

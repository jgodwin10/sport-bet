"""Google Gemini client with a rotating pool of API keys.

Requests start from the next key in round-robin order. A key that is rate-limited
(429), rejected (invalid/forbidden) or hits a server error is put on cooldown and
the request moves on to the next key, so one exhausted key does not stop analysis.
Models are tried in order: a model the API does not know (404) falls through to
the next one. Keys travel only in the `x-goog-api-key` header and are never logged
or included in error messages; the pool refers to them by slot number.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

RATE_LIMIT_COOLDOWN = 60.0
DAILY_QUOTA_COOLDOWN = 3600.0
REJECTED_KEY_COOLDOWN = 6 * 3600.0
SERVER_ERROR_COOLDOWN = 30.0


class GeminiError(RuntimeError):
    """The request itself failed (bad request, blocked or empty response)."""


class GeminiUnavailable(GeminiError):
    """No key/model combination could serve the request right now."""


class KeyPool:
    def __init__(self, keys: list[str], clock=time.monotonic) -> None:
        self._keys = list(dict.fromkeys(keys))
        self._until = [0.0] * len(self._keys)
        self._reason: list[str | None] = [None] * len(self._keys)
        self._next = 0
        self._clock = clock
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._keys)

    def order(self) -> list[tuple[int, str]]:
        """Usable (slot, key) pairs, starting from the next key in rotation."""
        with self._lock:
            n = len(self._keys)
            if not n:
                return []
            start = self._next
            self._next = (self._next + 1) % n
            now = self._clock()
            slots = [(start + i) % n for i in range(n)]
            return [(s, self._keys[s]) for s in slots if self._until[s] <= now]

    def penalise(self, slot: int, seconds: float, reason: str) -> None:
        with self._lock:
            self._until[slot] = max(self._until[slot], self._clock() + seconds)
            self._reason[slot] = reason
        log.warning("gemini key #%d cooling down for %.0fs: %s", slot + 1, seconds, reason)

    def succeeded(self, slot: int) -> None:
        with self._lock:
            self._reason[slot] = None

    def status(self) -> list[dict]:
        now = self._clock()
        with self._lock:
            return [{"slot": i + 1, "available": self._until[i] <= now,
                     "retry_in_seconds": max(0, round(self._until[i] - now)),
                     "last_problem": self._reason[i]} for i in range(len(self._keys))]


@dataclass
class GeminiResult:
    text: str
    model: str
    key_slot: int
    sources: list[dict] = field(default_factory=list)  # [{title, uri}]
    search_queries: list[str] = field(default_factory=list)


def _retry_delay(body: dict) -> float | None:
    for d in (body.get("error") or {}).get("details") or []:
        delay = d.get("retryDelay") if isinstance(d, dict) else None
        if isinstance(delay, str) and (m := re.fullmatch(r"(\d+(?:\.\d+)?)s", delay)):
            return float(m.group(1))
    return None


class GeminiClient:
    def __init__(self, keys: list[str], models: list[str], timeout: float = 120.0,
                 transport: httpx.BaseTransport | None = None, clock=time.monotonic) -> None:
        self.pool = KeyPool(keys, clock)
        self.models = models
        self._client = httpx.Client(timeout=timeout, transport=transport)

    @property
    def configured(self) -> bool:
        return len(self.pool) > 0 and bool(self.models)

    def status(self) -> dict:
        return {"configured": self.configured, "models": self.models, "keys": self.pool.status()}

    def generate(self, prompt: str, *, system: str | None = None, search: bool = True,
                 temperature: float = 0.3) -> GeminiResult:
        if not self.configured:
            raise GeminiUnavailable("Gemini is not configured (set GEMINI_API_KEYS)")
        body: dict = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                      "generationConfig": {"temperature": temperature}}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if search:
            body["tools"] = [{"google_search": {}}]

        problems: list[str] = []
        for model in self.models:
            candidates = self.pool.order()
            if not candidates:
                break
            for slot, key in candidates:
                outcome = self._attempt(model, slot, key, body)
                if isinstance(outcome, GeminiResult):
                    return outcome
                problems.append(f"{model} key #{slot + 1}: {outcome}")
                if outcome == "model unavailable":
                    break  # same answer for every key: try the next model
        cooling = sum(not k["available"] for k in self.pool.status())
        raise GeminiUnavailable(
            f"no Gemini key could serve the request ({cooling}/{len(self.pool)} keys cooling down)"
            + (f"; last problems: {'; '.join(problems[-3:])}" if problems else ""))

    def _attempt(self, model: str, slot: int, key: str, body: dict) -> GeminiResult | str:
        try:
            resp = self._client.post(f"{BASE_URL}/models/{model}:generateContent", json=body,
                                     headers={"x-goog-api-key": key})
        except httpx.TransportError as exc:
            self.pool.penalise(slot, SERVER_ERROR_COOLDOWN, f"network error ({type(exc).__name__})")
            return "network error"
        try:
            data = resp.json()
        except ValueError:
            data = {}
        err = (data.get("error") or {}) if isinstance(data, dict) else {}
        message = str(err.get("message", ""))
        text_blob = json.dumps(err)

        if resp.status_code == 200:
            self.pool.succeeded(slot)
            return self._parse(data, model, slot)
        if resp.status_code == 429:
            daily = "PerDay" in text_blob or "per day" in text_blob.lower()
            delay = DAILY_QUOTA_COOLDOWN if daily else (_retry_delay(data) or RATE_LIMIT_COOLDOWN)
            self.pool.penalise(slot, delay, "daily quota exhausted" if daily else "rate limited")
            return "rate limited"
        if resp.status_code in (401, 403) or "API_KEY_INVALID" in text_blob or "API key not valid" in message:
            self.pool.penalise(slot, REJECTED_KEY_COOLDOWN, f"key rejected (HTTP {resp.status_code})")
            return "key rejected"
        if resp.status_code == 404:
            return "model unavailable"
        if resp.status_code >= 500:
            self.pool.penalise(slot, SERVER_ERROR_COOLDOWN, f"server error (HTTP {resp.status_code})")
            return f"server error {resp.status_code}"
        # Any other 4xx is a problem with the request, which another key would not fix.
        raise GeminiError(f"Gemini rejected the request (HTTP {resp.status_code}): {message[:200]}")

    @staticmethod
    def _parse(data: dict, model: str, slot: int) -> GeminiResult:
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise GeminiError(f"Gemini returned no answer ({reason})")
        cand = candidates[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            raise GeminiError(f"Gemini returned an empty answer ({cand.get('finishReason', 'unknown')})")
        meta = cand.get("groundingMetadata") or {}
        sources, seen = [], set()
        for chunk in meta.get("groundingChunks") or []:
            web = chunk.get("web") or {}
            if web.get("uri") and web["uri"] not in seen:
                seen.add(web["uri"])
                sources.append({"title": web.get("title") or web["uri"], "uri": web["uri"]})
        return GeminiResult(text=text, model=model, key_slot=slot + 1, sources=sources,
                            search_queries=list(meta.get("webSearchQueries") or []))


_client: GeminiClient | None = None
_client_lock = threading.Lock()


def get_gemini() -> GeminiClient:
    """Process-wide client, so key cooldowns are shared by all requests in this process."""
    global _client
    with _client_lock:
        if _client is None:
            from app.core.config import get_settings

            s = get_settings()
            _client = GeminiClient(s.gemini_key_list, s.gemini_model_list, timeout=s.gemini_timeout_seconds)
        return _client

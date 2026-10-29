"""OpenAI client (Responses API with the web search tool) with a rotating pool of API keys.

It follows the Gemini client's rules: requests start from the next key in round-robin
order; a rejected key cools down for every model, a rate limit only for that model, and an
exhausted billing quota for every model until the next hour. A model the account cannot use
(unknown, no access, or no web search support) falls through to the next one in OPENAI_MODELS.
Keys travel only in the Authorization header and are never logged or included in error
messages; the pool refers to them by slot number.
"""

from __future__ import annotations

import logging
import threading
import time

import httpx

from app.providers.ai import AiError, AiResult, AiUnavailable
from app.providers.gemini import (
    DAILY_QUOTA_COOLDOWN, RATE_LIMIT_COOLDOWN, REJECTED_KEY_COOLDOWN, SERVER_ERROR_COOLDOWN, KeyPool,
)

log = logging.getLogger(__name__)

BASE_URL = "https://api.openai.com/v1"
MODEL_UNAVAILABLE_CODES = {"model_not_found", "unsupported_model"}


class OpenAiError(AiError):
    """The request itself failed (bad request, refused or empty response)."""


class OpenAiUnavailable(OpenAiError, AiUnavailable):
    """No key/model combination could serve the request right now."""


def _retry_after(resp: httpx.Response) -> float | None:
    for header, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        try:
            return float(resp.headers[header]) * scale
        except (KeyError, ValueError):
            continue
    return None


class OpenAiClient:
    name = "openai"

    def __init__(self, keys: list[str], models: list[str], timeout: float = 180.0,
                 transport: httpx.BaseTransport | None = None, clock=time.monotonic) -> None:
        self.pool = KeyPool(keys, clock)
        self.models = models
        self._client = httpx.Client(timeout=timeout, transport=transport)

    @property
    def configured(self) -> bool:
        return len(self.pool) > 0 and bool(self.models)

    def status(self) -> dict:
        return {"configured": self.configured, "models": self.models, "keys": self.pool.status(self.models)}

    def generate(self, prompt: str, *, system: str | None = None, search: bool = True,
                 temperature: float = 0.3) -> AiResult:
        """`temperature` is not sent: OpenAI's reasoning models reject it."""
        if not self.configured:
            raise OpenAiUnavailable("OpenAI is not configured (set OPENAI_API_KEYS)")
        body: dict = {"input": prompt}
        if system:
            body["instructions"] = system
        if search:
            body["tools"] = [{"type": "web_search"}]

        problems: list[str] = []
        for i, model in enumerate(self.models):
            for slot, key in self.pool.order(model, advance=i == 0):
                outcome = self._attempt(model, slot, key, {"model": model, **body})
                if isinstance(outcome, AiResult):
                    return outcome
                problems.append(f"{model} key #{slot + 1}: {outcome}")
                if outcome == "model unavailable":
                    break  # same answer for every key: try the next model
        cooling = sum(not k["available"] for k in self.pool.status(self.models))
        raise OpenAiUnavailable(
            f"no OpenAI key could serve the request ({cooling}/{len(self.pool)} keys cooling down)"
            + (f"; last problems: {'; '.join(problems[-3:])}" if problems else ""))

    def _attempt(self, model: str, slot: int, key: str, body: dict) -> AiResult | str:
        try:
            resp = self._client.post(f"{BASE_URL}/responses", json=body,
                                     headers={"Authorization": f"Bearer {key}"})
        except httpx.TransportError as exc:
            self.pool.penalise(slot, SERVER_ERROR_COOLDOWN, f"network error ({type(exc).__name__})")
            return "network error"
        try:
            data = resp.json()
        except ValueError:
            data = {}
        err = (data.get("error") or {}) if isinstance(data, dict) else {}
        code, message = str(err.get("code") or err.get("type") or ""), str(err.get("message", ""))

        if resp.status_code == 200:
            self.pool.succeeded(slot)
            return self._parse(data, model, slot)
        if resp.status_code == 429:
            if code == "insufficient_quota":  # out of credit: no model on this key will work
                self.pool.penalise(slot, DAILY_QUOTA_COOLDOWN, "billing quota exhausted")
                return "quota exhausted"
            self.pool.penalise(slot, _retry_after(resp) or RATE_LIMIT_COOLDOWN, "rate limited", model)
            return "rate limited"
        if resp.status_code in (401, 403) and code not in MODEL_UNAVAILABLE_CODES:
            self.pool.penalise(slot, REJECTED_KEY_COOLDOWN, f"key rejected (HTTP {resp.status_code})")
            return "key rejected"
        if (resp.status_code == 404 or code in MODEL_UNAVAILABLE_CODES
                or (resp.status_code == 400 and err.get("param") in ("model", "tools"))):
            return "model unavailable"
        if resp.status_code >= 500:
            self.pool.penalise(slot, SERVER_ERROR_COOLDOWN, f"server error (HTTP {resp.status_code})", model)
            return f"server error {resp.status_code}"
        # Any other 4xx is a problem with the request, which another key would not fix.
        raise OpenAiError(f"OpenAI rejected the request (HTTP {resp.status_code}): {message[:200]}")

    @staticmethod
    def _parse(data: dict, model: str, slot: int) -> AiResult:
        texts, sources, queries, seen = [], [], [], set()
        for item in data.get("output") or []:
            if item.get("type") == "web_search_call":
                action = item.get("action") or {}
                for q in [action.get("query"), *(action.get("queries") or [])]:
                    if isinstance(q, str) and q and q not in queries:
                        queries.append(q)
            elif item.get("type") == "message":
                for part in item.get("content") or []:
                    if part.get("type") == "refusal":
                        raise OpenAiError(f"OpenAI refused to answer ({str(part.get('refusal', ''))[:200]})")
                    if part.get("type") != "output_text":
                        continue
                    texts.append(part.get("text", ""))
                    for a in part.get("annotations") or []:
                        if a.get("type") == "url_citation" and a.get("url") and a["url"] not in seen:
                            seen.add(a["url"])
                            sources.append({"title": a.get("title") or a["url"], "uri": a["url"]})
        text = "".join(texts)
        if not text.strip():
            reason = (data.get("incomplete_details") or {}).get("reason") or data.get("status") or "unknown"
            raise OpenAiError(f"OpenAI returned an empty answer ({reason})")
        return AiResult(text=text, model=model, key_slot=slot + 1, provider="openai", sources=sources,
                        search_queries=queries)


_client: OpenAiClient | None = None
_client_lock = threading.Lock()


def get_openai() -> OpenAiClient:
    """Process-wide client, so key cooldowns are shared by all requests in this process."""
    global _client
    with _client_lock:
        if _client is None:
            from app.core.config import get_settings

            s = get_settings()
            _client = OpenAiClient(s.openai_key_list, s.openai_model_list, timeout=s.openai_timeout_seconds)
        return _client

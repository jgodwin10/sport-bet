"""Shared types for the LLM providers behind AI match analysis, and the chain that tries them
in order (AI_PROVIDERS, e.g. "openai,gemini"): a provider with no key is skipped, and one whose
keys are all cooling down hands the request to the next. Each provider rotates its own keys."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Protocol


class AiError(RuntimeError):
    """The request itself failed (bad request, blocked or empty response)."""

    provider: str | None = None  # set by AiChain to the provider that failed


class AiUnavailable(AiError):
    """No key/model combination could serve the request right now."""


@dataclass
class AiResult:
    text: str
    model: str
    key_slot: int
    provider: str = "gemini"
    sources: list[dict] = field(default_factory=list)  # [{title, uri}]
    search_queries: list[str] = field(default_factory=list)


class AiClient(Protocol):
    name: str

    @property
    def configured(self) -> bool: ...

    def status(self) -> dict: ...

    def generate(self, prompt: str, *, system: str | None = None, search: bool = True,
                 temperature: float = 0.3) -> AiResult: ...


class AiChain:
    def __init__(self, clients: list[AiClient]) -> None:
        self.clients = clients

    @property
    def configured(self) -> bool:
        return any(c.configured for c in self.clients)

    def status(self) -> dict:
        """`keys` and `models` cover every configured provider, in the order they are tried."""
        providers = [{"name": c.name, **c.status()} for c in self.clients]
        active = [p for p in providers if p["configured"]]
        return {"configured": bool(active), "providers": providers,
                "models": [f"{p['name']}:{m}" for p in active for m in p["models"]],
                "keys": [{**k, "provider": p["name"]} for p in active for k in p["keys"]]}

    def generate(self, prompt: str, *, system: str | None = None, search: bool = True,
                 temperature: float = 0.3) -> AiResult:
        problems = []
        for client in self.clients:
            if not client.configured:
                continue
            try:
                return client.generate(prompt, system=system, search=search, temperature=temperature)
            except AiUnavailable as exc:
                problems.append(f"{client.name}: {exc}")
            except AiError as exc:
                exc.provider = client.name
                raise
        if not problems:
            raise AiUnavailable("AI analysis is not configured (set OPENAI_API_KEYS or GEMINI_API_KEYS)")
        raise AiUnavailable("; ".join(problems))


_chain: AiChain | None = None
_chain_lock = threading.Lock()


def get_ai() -> AiChain:
    """Process-wide chain, so key cooldowns are shared by all requests in this process."""
    global _chain
    with _chain_lock:
        if _chain is None:
            from app.core.config import get_settings
            from app.providers.gemini import get_gemini
            from app.providers.openai import get_openai

            known = {"openai": get_openai, "gemini": get_gemini}
            _chain = AiChain([known[n]() for n in get_settings().ai_provider_list if n in known])
        return _chain

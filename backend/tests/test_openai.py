"""OpenAI client, the provider chain and the analysis service on OpenAI. All HTTP traffic is
mocked; keys and payloads are SYNTHETIC."""

import json

import httpx
import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.db.models import AiAnalysis
from app.providers.ai import AiChain, AiError, AiUnavailable
from app.providers.openai import OpenAiClient, OpenAiError, OpenAiUnavailable
from app.services import ai_analysis
from app.services.ai_analysis import AiAnalysisService
from tests.test_ai_analysis import ANSWER, Clock, _upcoming, client_with, fake, ok_body  # noqa: F401


def openai_body(text: str) -> dict:
    return {"status": "completed", "output": [
        {"type": "reasoning", "summary": []},
        {"type": "web_search_call", "status": "completed",
         "action": {"type": "search", "query": "synthetic town injuries"}},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text, "annotations": [
            {"type": "url_citation", "url": "https://news.example/a", "title": "Example news"},
            {"type": "url_citation", "url": "https://news.example/a", "title": "duplicate"}]}]}]}


def openai_with(handler, keys=("key-aaa", "key-bbb"), models=("model-new", "model-old"), clock=None):
    return OpenAiClient(list(keys), list(models), transport=httpx.MockTransport(handler), clock=clock or Clock())


def _err(status: int, code: str, message: str = "problem", param: str | None = None, **kw) -> httpx.Response:
    return httpx.Response(status, json={"error": {"message": message, "type": code, "code": code, "param": param}},
                          **kw)


def test_settings_parse_openai_keys_models_and_provider_order():
    s = Settings(openai_api_keys=" k1, k2,\nk1 ", openai_models="a, b", ai_providers="OpenAI, gemini")
    assert s.openai_key_list == ["k1", "k2"] and s.openai_model_list == ["a", "b"]
    assert s.ai_provider_list == ["openai", "gemini"]
    assert Settings(openai_api_keys=None).openai_key_list == []


def test_request_shape_and_parsing():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=openai_body("{}"))

    r = openai_with(handler).generate("prompt", system="sys")
    body = json.loads(seen[0].content)
    assert str(seen[0].url) == "https://api.openai.com/v1/responses"
    assert seen[0].headers["authorization"] == "Bearer key-aaa"
    assert body == {"model": "model-new", "input": "prompt", "instructions": "sys", "tools": [{"type": "web_search"}]}
    assert "temperature" not in body  # reasoning models reject it
    assert (r.provider, r.model, r.key_slot, r.text) == ("openai", "model-new", 1, "{}")
    assert r.sources == [{"title": "Example news", "uri": "https://news.example/a"}]
    assert r.search_queries == ["synthetic town injuries"]
    openai_with(handler).generate("p", search=False)
    assert "tools" not in json.loads(seen[-1].content) and "instructions" not in json.loads(seen[-1].content)


def test_rate_limit_rotates_keys_and_quota_cools_the_whole_key():
    clock = Clock()

    def handler(req: httpx.Request) -> httpx.Response:
        if req.headers["authorization"] == "Bearer key-aaa":
            return _err(429, "rate_limit_exceeded", headers={"retry-after": "20"})
        return httpx.Response(200, json=openai_body("ok"))

    c = openai_with(handler, clock=clock)
    assert c.generate("p").key_slot == 2
    k1 = c.status()["keys"][0]
    assert k1["cooling_models"] == {"model-new": 20} and k1["available"]  # model-old still usable

    def broke(req: httpx.Request) -> httpx.Response:
        return _err(429, "insufficient_quota", "You exceeded your current quota")

    c = openai_with(broke, clock=clock)
    with pytest.raises(OpenAiUnavailable, match="2/2 keys cooling down"):
        c.generate("p")
    assert all(k["retry_in_seconds"] == 3600 for k in c.status()["keys"])


def test_unusable_model_falls_through_and_bad_key_is_rejected():
    def handler(req: httpx.Request) -> httpx.Response:
        model = json.loads(req.content)["model"]
        if model == "model-new":
            return _err(404, "model_not_found", "The model `model-new` does not exist")
        if req.headers["authorization"] == "Bearer key-aaa":
            return _err(401, "invalid_api_key", "Incorrect API key provided: key-aaa")
        return httpx.Response(200, json=openai_body("ok"))

    c = openai_with(handler)
    r = c.generate("p")
    assert (r.model, r.key_slot) == ("model-old", 2)
    assert c.status()["keys"][0]["last_problem"] == "key rejected (HTTP 401)"

    def no_search(req: httpx.Request) -> httpx.Response:
        if json.loads(req.content)["model"] == "model-new":
            return _err(400, "invalid_request_error", "web_search is not supported", param="tools")
        return httpx.Response(200, json=openai_body("ok"))

    assert openai_with(no_search).generate("p").model == "model-old"


def test_request_errors_refusals_and_empty_answers_are_errors_not_rotation():
    calls = []

    def bad(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _err(400, "invalid_request_error", "Invalid input", param="input")

    with pytest.raises(OpenAiError, match="Invalid input"):
        openai_with(bad).generate("p")
    assert len(calls) == 1

    refusal = {"output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}]}
    with pytest.raises(OpenAiError, match="refused"):
        openai_with(lambda r: httpx.Response(200, json=refusal)).generate("p")
    empty = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": []}
    with pytest.raises(OpenAiError, match="max_output_tokens"):
        openai_with(lambda r: httpx.Response(200, json=empty)).generate("p")


def test_errors_never_leak_keys():
    def handler(req: httpx.Request) -> httpx.Response:
        return _err(401, "invalid_api_key", "Incorrect API key provided: key-aaa")

    with pytest.raises(OpenAiUnavailable) as exc:
        openai_with(handler).generate("p")
    assert "key-aaa" not in str(exc.value) and "key-bbb" not in str(exc.value)


def test_chain_prefers_first_provider_and_falls_back_when_unavailable():
    def limited(req: httpx.Request) -> httpx.Response:
        return _err(429, "insufficient_quota")

    gemini = client_with(lambda r: httpx.Response(200, json=ok_body("from gemini")))
    working = AiChain([openai_with(lambda r: httpx.Response(200, json=openai_body("from openai"))), gemini])
    assert working.generate("p").provider == "openai"
    fallback = AiChain([openai_with(limited), gemini])
    r = fallback.generate("p")
    assert (r.provider, r.text) == ("gemini", "from gemini")
    # A provider without keys is skipped; status lists keys of configured providers only
    chain = AiChain([OpenAiClient([], ["m"]), gemini])
    assert chain.configured and chain.generate("p").provider == "gemini"
    st = chain.status()
    assert st["models"][0] == "gemini:model-new" and {k["provider"] for k in st["keys"]} == {"gemini"}
    with pytest.raises(AiUnavailable, match="not configured"):
        AiChain([OpenAiClient([], ["m"])]).generate("p")


def test_chain_does_not_hide_request_errors_behind_the_fallback():
    def bad(req: httpx.Request) -> httpx.Response:
        return _err(400, "invalid_request_error", "Invalid input", param="input")

    gemini_calls = []
    gemini = client_with(lambda r: gemini_calls.append(1) or httpx.Response(200, json=ok_body("x")))
    with pytest.raises(AiError) as exc:
        AiChain([openai_with(bad), gemini]).generate("p")
    assert exc.value.provider == "openai" and not gemini_calls


def test_service_stores_openai_analysis(db, fake, monkeypatch):
    chain = AiChain([openai_with(lambda r: httpx.Response(200, json=openai_body(json.dumps(ANSWER))),
                                 keys=["fake-openai-key"]), fake.client])
    monkeypatch.setattr(ai_analysis, "get_ai", lambda: chain)
    row = AiAnalysisService(db, get_settings()).analyse(_upcoming(db))
    assert (row.status, row.provider, row.model) == ("ok", "openai", "model-new")
    assert row.content["summary"] == ANSWER["summary"] and row.search_queries == ["synthetic town injuries"]
    assert fake.calls == 0


def test_service_records_which_provider_failed(db, fake, monkeypatch):
    bad = openai_with(lambda r: _err(400, "invalid_request_error", "Invalid input", param="input"))
    monkeypatch.setattr(ai_analysis, "get_ai", lambda: AiChain([bad]))
    row = AiAnalysisService(db, get_settings()).analyse(_upcoming(db))
    assert (row.status, row.provider) == ("failed", "openai") and "Invalid input" in row.error
    assert db.scalar(select(AiAnalysis.provider)) == "openai"

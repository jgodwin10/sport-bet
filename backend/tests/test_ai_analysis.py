"""Gemini key rotation, response parsing and the AI analysis API. All HTTP traffic is
mocked; keys and payloads are SYNTHETIC."""

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.db.models import AiAnalysis, Fixture, Prediction, User
from app.ingestion.store import Store
from app.main import create_app
from app.providers.gemini import GeminiClient, GeminiError, GeminiUnavailable, KeyPool
from app.services import ai_analysis
from app.services.ai_analysis import AiAnalysisService, normalise
from app.services.prediction import PredictionService
from tests.conftest import make_batch, synthetic_league

ANSWER = {
    "summary": "Home side should control the game.",
    "key_factors": [{"title": "Striker out", "detail": "Main striker injured.", "favours": "away",
                     "weight": "high", "basis": "news"}],
    "team_news": [{"team": "Synthetic Town 01", "detail": "Striker ruled out (hamstring).", "status": "confirmed"}],
    "risks": ["Late lineup changes"],
    "model_assessment": "News weakens the home side slightly.",
    "probability_view": {"home": 45, "draw": 28, "away": 27},
    "confidence": "medium",
}


def ok_body(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "groundingMetadata": {
        "webSearchQueries": ["synthetic town injuries"],
        "groundingChunks": [{"web": {"uri": "https://news.example/a", "title": "Example news"}},
                            {"web": {"uri": "https://news.example/a", "title": "duplicate"}}]}}]}


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def client_with(handler, keys=("key-aaa", "key-bbb", "key-ccc"), models=("model-new", "model-old"), clock=None):
    return GeminiClient(list(keys), list(models), transport=httpx.MockTransport(handler), clock=clock or Clock())


def test_settings_parse_comma_separated_keys_and_models():
    s = Settings(gemini_api_keys=" k1, k2,\nk3 ,k1 ", gemini_models="a, b")
    assert s.gemini_key_list == ["k1", "k2", "k3"]
    assert s.gemini_model_list == ["a", "b"]
    assert Settings(gemini_api_keys=None).gemini_key_list == []


def test_rate_limited_key_fails_over_to_next_key_and_cools_down():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        key = req.headers["x-goog-api-key"]
        seen.append(key)
        assert "key=" not in str(req.url)  # keys never go in the URL
        if key == "key-aaa":
            return httpx.Response(429, json={"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}]}})
        return httpx.Response(200, json=ok_body("hello"))

    clock = Clock()
    c = client_with(handler, clock=clock)
    r = c.generate("prompt")
    assert r.text == "hello" and r.key_slot == 2 and r.model == "model-new"
    assert r.sources == [{"title": "Example news", "uri": "https://news.example/a"}]
    assert r.search_queries == ["synthetic town injuries"]
    status = c.pool.status()
    assert status[0]["available"] is False and status[0]["retry_in_seconds"] == 37
    # next request starts after the cooling key and never touches it
    seen.clear()
    c.generate("prompt")
    c.generate("prompt")
    assert "key-aaa" not in seen
    clock.t += 40
    assert c.pool.status()[0]["available"] is True


def test_daily_quota_and_invalid_key_get_long_cooldowns():
    def handler(req: httpx.Request) -> httpx.Response:
        key = req.headers["x-goog-api-key"]
        if key == "key-aaa":
            return httpx.Response(429, json={"error": {"message": "Quota exceeded for metric "
                                                       "generate_content_free_tier_requests, limit: PerDay"}})
        if key == "key-bbb":
            return httpx.Response(400, json={"error": {"code": 400, "message": "API key not valid. Please pass a "
                                                       "valid API key.", "details": [{"reason": "API_KEY_INVALID"}]}})
        return httpx.Response(200, json=ok_body("ok"))

    c = client_with(handler)
    assert c.generate("p").key_slot == 3
    s = c.pool.status()
    assert s[0]["retry_in_seconds"] == 3600 and s[0]["last_problem"] == "daily quota exhausted"
    assert s[1]["retry_in_seconds"] == 6 * 3600 and "rejected" in s[1]["last_problem"]


def test_unknown_model_falls_back_to_next_model():
    def handler(req: httpx.Request) -> httpx.Response:
        if "model-new" in req.url.path:
            return httpx.Response(404, json={"error": {"code": 404, "message": "models/model-new is not found"}})
        return httpx.Response(200, json=ok_body("from old"))

    c = client_with(handler)
    r = c.generate("p")
    assert r.model == "model-old" and r.text == "from old"
    assert all(k["available"] for k in c.pool.status())  # a missing model is not the key's fault


def test_all_keys_exhausted_raises_unavailable_without_leaking_keys():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "overloaded"}})

    c = client_with(handler)
    with pytest.raises(GeminiUnavailable) as exc:
        c.generate("p")
    assert "key-" not in str(exc.value)
    with pytest.raises(GeminiUnavailable, match="3/3 keys cooling down"):
        c.generate("p")


def test_bad_request_and_blocked_answers_are_errors_not_rotation():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "Invalid JSON payload"}})

    with pytest.raises(GeminiError, match="Invalid JSON payload"):
        client_with(handler).generate("p")
    assert len(calls) == 1
    blocked = client_with(lambda r: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(GeminiError, match="SAFETY"):
        blocked.generate("p")


def test_request_shape_has_search_tool_and_system_instruction():
    bodies = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json=ok_body("x"))

    c = client_with(handler, keys=["k"])
    c.generate("p", system="sys", search=True)
    c.generate("p", search=False)
    assert bodies[0]["tools"] == [{"google_search": {}}]
    assert bodies[0]["systemInstruction"]["parts"][0]["text"] == "sys"
    assert "tools" not in bodies[1]


def test_unconfigured_client_and_rotation_order():
    with pytest.raises(GeminiUnavailable, match="not configured"):
        GeminiClient([], ["m"]).generate("p")
    pool = KeyPool(["a", "b", "c"])
    assert [s for s, _ in pool.order()] == [0, 1, 2]
    assert [s for s, _ in pool.order()] == [1, 2, 0]


def test_normalise_validates_and_rescales():
    out = normalise("```json\n" + json.dumps({**ANSWER, "confidence": "certain",
                                              "key_factors": [*ANSWER["key_factors"], {"detail": "no title"}]}) + "\n```")
    assert out["structured"] is True
    assert out["probability_view"] == pytest.approx({"home": 0.45, "draw": 0.28, "away": 0.27})
    assert out["confidence"] == "low"  # unknown value -> conservative default
    assert len(out["key_factors"]) == 1 and out["key_factors"][0]["favours"] == "away"
    junk = normalise("The home team looks stronger.")
    assert junk["structured"] is False and junk["summary"].startswith("The home team")
    assert junk["probability_view"] is None
    assert normalise(json.dumps({**ANSWER, "probability_view": {"home": 0.9, "draw": 0.9, "away": 0.9}}))[
        "probability_view"] is None


# ------------------------------------------------------------------ service + API
START = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=365 * 2 + 20)


class FakeGemini:
    def __init__(self) -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self.client = client_with(self._handle, keys=["fake-key"])

    def _handle(self, req: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.prompts.append(json.loads(req.content)["contents"][0]["parts"][0]["text"])
        return httpx.Response(200, json=ok_body(json.dumps(ANSWER)))


@pytest.fixture()
def fake(db, monkeypatch):
    fixtures = synthetic_league(START, seasons=3, upcoming_after=datetime.now(timezone.utc))
    Store(db).ingest_fixtures(make_batch(fixtures))
    db.add(User(email="viewer@example.com", password_hash=hash_password("viewer-password-1"), role="viewer"))
    db.commit()
    PredictionService(db, get_settings()).predict_upcoming("test")
    g = FakeGemini()
    monkeypatch.setattr(ai_analysis, "get_gemini", lambda: g.client)
    return g


def _upcoming(db) -> Fixture:
    return db.scalar(select(Fixture).join(Prediction, Prediction.fixture_id == Fixture.id)
                     .where(Fixture.status == "scheduled").order_by(Fixture.kickoff_utc).limit(1))


def test_service_builds_prompt_stores_analysis_and_reuses_it(db, fake):
    f = _upcoming(db)
    svc = AiAnalysisService(db, get_settings())
    row = svc.analyse(f, requested_by="t")
    assert row.status == "ok" and row.model == "model-new" and row.key_slot == 1
    assert row.content["team_news"][0]["status"] == "confirmed"
    assert row.content["basis"]["model_1x2"]["home"] > 0
    assert row.sources == [{"title": "Example news", "uri": "https://news.example/a"}]
    prompt = fake.prompts[0]
    assert f.home_team.name in prompt and "1X2: home" in prompt and "[form]" in prompt
    # same prediction snapshot -> no second API call
    assert svc.analyse(f).id == row.id and fake.calls == 1


def test_service_refuses_after_kickoff(db, fake):
    f = _upcoming(db)
    with pytest.raises(ValueError, match="before kickoff"):
        AiAnalysisService(db, get_settings()).analyse(f, now=f.kickoff_utc + timedelta(minutes=1))
    assert fake.calls == 0


def test_scheduled_run_respects_cap_and_staleness(db, fake, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "gemini_auto_hours", 24 * 30)
    monkeypatch.setattr(s, "gemini_auto_max_per_run", 2)
    svc = AiAnalysisService(db, s)
    first = svc.analyse_upcoming()
    assert first["analysed"] == 2 and fake.calls == 2
    svc.analyse_upcoming()
    assert fake.calls == 4  # the next two fixtures, not the same ones again
    assert db.scalar(select(AiAnalysis.id).where(AiAnalysis.status != "ok")) is None


def test_api_get_and_post(db, fake):
    f = _upcoming(db)
    with TestClient(create_app()) as c:
        r = c.get(f"/api/v1/fixtures/{f.id}/ai-analysis").json()
        assert r["configured"] is True and r["available"] is True and r["analysis"] is None
        assert c.post(f"/api/v1/fixtures/{f.id}/ai-analysis").status_code == 401
        tok = c.post("/api/v1/auth/login", json={"email": "viewer@example.com",
                                                 "password": "viewer-password-1"}).json()["access_token"]
        r = c.post(f"/api/v1/fixtures/{f.id}/ai-analysis", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, r.text
        assert r.json()["content"]["summary"] == ANSWER["summary"]
        got = c.get(f"/api/v1/fixtures/{f.id}/ai-analysis").json()["analysis"]
        assert got["id"] == r.json()["id"]
        health = c.get("/api/v1/system/health").text
        assert "fake-key" not in health


def test_api_reports_unconfigured(db, monkeypatch):
    fixtures = synthetic_league(START, seasons=1, upcoming_after=datetime.now(timezone.utc))
    Store(db).ingest_fixtures(make_batch(fixtures))
    db.commit()
    monkeypatch.setattr(ai_analysis, "get_gemini", lambda: GeminiClient([], ["m"]))
    f = db.scalar(select(Fixture).limit(1))
    with TestClient(create_app()) as c:
        assert c.get(f"/api/v1/fixtures/{f.id}/ai-analysis").json()["configured"] is False

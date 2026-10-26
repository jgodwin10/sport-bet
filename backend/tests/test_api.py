"""API contract, validation, auth and responsible-betting controls. Data SYNTHETIC."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import Selection, User
from app.ingestion.store import Store
from app.main import create_app
from app.services.prediction import PredictionService
from tests.conftest import make_batch, synthetic_league

START = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=365 * 2 + 20)


@pytest.fixture()
def client(db):
    fixtures = synthetic_league(START, seasons=3, upcoming_after=datetime.now(timezone.utc))
    Store(db).ingest_fixtures(make_batch(fixtures))
    db.add(User(email="admin@example.com", password_hash=hash_password("admin-password-1"), role="admin"))
    db.add(User(email="viewer@example.com", password_hash=hash_password("viewer-password-1"), role="viewer"))
    db.commit()
    PredictionService(db, get_settings()).predict_upcoming("test")
    with TestClient(create_app()) as c:
        yield c


def _token(client, email, password):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_health_and_security_headers(client):
    r = client.get("/api/v1/system/health")
    assert r.status_code == 200
    assert r.json()["checks"]["database"] == "ok"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "x-request-id" in r.headers


def test_providers_never_expose_keys(client):
    body = client.get("/api/v1/system/providers").text.lower()
    assert "apikey" not in body and "secret" not in body


def test_fixture_list_and_analysis(client):
    r = client.get("/api/v1/fixtures", params={"page_size": 5, "status": "scheduled"})
    assert r.status_code == 200
    page = r.json()
    assert page["total"] > 0 and len(page["items"]) <= 5
    fx = page["items"][0]
    assert fx["latest_prediction"] is not None
    a = client.get(f"/api/v1/fixtures/{fx['id']}/analysis").json()
    assert a["prediction"]["markets"]["1x2"]
    assert a["form"]["home"]["summary"]["last_5"]["matches"] == 5
    assert a["disclaimer"]
    assert a["prediction"]["explanations"]
    assert a["odds"]["latest"]


def test_fixture_not_found_and_validation(client):
    assert client.get("/api/v1/fixtures/999999").status_code == 404
    r = client.get("/api/v1/fixtures", params={"status": "bogus"})
    assert r.status_code == 422 and r.json()["detail"] == "validation error"
    assert client.get("/api/v1/fixtures", params={"page_size": 1000}).status_code == 422


def test_predictions_filters_and_sorting(client):
    r = client.get("/api/v1/predictions", params={"market": "1x2", "sort": "probability", "order": "desc"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items and all(i["market"] == "1x2" for i in items)
    probs = [i["probability"] for i in items]
    assert probs == sorted(probs, reverse=True)
    assert all(i["status"] == "upcoming" for i in items)
    r = client.get("/api/v1/predictions", params={"min_odds": 2.5})
    assert all(i["odds"] >= 2.5 for i in r.json()["items"])


def test_admin_endpoints_require_admin(client):
    assert client.post("/api/v1/admin/ingest", json={"kind": "settle"}).status_code == 401
    viewer = _token(client, "viewer@example.com", "viewer-password-1")
    assert client.post("/api/v1/admin/ingest", json={"kind": "settle"}, headers=viewer).status_code == 403
    admin = _token(client, "admin@example.com", "admin-password-1")
    assert client.post("/api/v1/admin/ingest", json={"kind": "settle"}, headers=admin).status_code == 202
    assert client.get("/api/v1/admin/audit", headers=admin).json()[0]["action"] == "ingest.settle"


def test_login_failures(client):
    assert client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "wrong-pass"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "not-an-email", "password": "whatever1"}).status_code == 422
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_settings_update_requires_admin_and_validates(client):
    body = {"rules": {"min_edge": 0.05}}
    assert client.put("/api/v1/settings", json=body).status_code == 401
    admin = _token(client, "admin@example.com", "admin-password-1")
    assert client.put("/api/v1/settings", json={"rules": {"min_probability": 2}}, headers=admin).status_code == 422
    r = client.put("/api/v1/settings", json=body, headers=admin)
    assert r.status_code == 200 and r.json()["rules"]["min_edge"] == 0.05
    assert r.json()["options"]["notifications_enabled"] is False  # opt-in by default


def test_backtest_request_validation(client):
    admin = _token(client, "admin@example.com", "admin-password-1")
    bad = {"competitions": ["ENG-1"], "date_from": "2026-01-01", "date_to": "2025-01-01"}
    assert client.post("/api/v1/backtests", json=bad, headers=admin).status_code == 422
    unknown = {"competitions": ["XXX-9"], "date_from": "2025-01-01", "date_to": "2026-01-01"}
    assert client.post("/api/v1/backtests", json=unknown, headers=admin).status_code == 422


def test_stake_tracking_is_opt_in_and_limited(client, db):
    viewer = _token(client, "viewer@example.com", "viewer-password-1")
    sel_id = db.scalar(select(Selection.id))
    assert client.post("/api/v1/stakes", json={"selection_id": sel_id, "stake": 1}, headers=viewer).status_code == 400
    admin = _token(client, "admin@example.com", "admin-password-1")
    client.put("/api/v1/settings", json={"options": {"stake_tracking_enabled": True, "max_stake_per_selection": 2,
                                                     "max_daily_stake": 3}}, headers=admin)
    assert client.post("/api/v1/stakes", json={"selection_id": sel_id, "stake": 5}, headers=viewer).status_code == 400
    assert client.post("/api/v1/stakes", json={"selection_id": sel_id, "stake": 2}, headers=viewer).status_code == 200
    r = client.post("/api/v1/stakes", json={"selection_id": sel_id, "stake": 2}, headers=viewer)
    assert r.status_code == 400 and "24h" in r.json()["detail"]


def test_performance_endpoints_report_empty_honestly(client):
    r = client.get("/api/v1/performance/summary").json()
    assert r["prospective"]["overall"]["selections"] == 0
    assert "losing" in r["disclosure"]
    assert client.get("/api/v1/performance/markets").status_code == 200


def test_team_statistics(client, db):
    team_id = client.get("/api/v1/teams", params={"search": "Synthetic Town 01"}).json()[0]["id"]
    r = client.get(f"/api/v1/teams/{team_id}/statistics").json()
    assert r["form"]["last_10"]["matches"] == 10
    assert r["elo_history"]


def test_rate_limit(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 3)
    with TestClient(create_app()) as c:
        codes = [c.get("/api/v1/competitions").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[-1] == 429

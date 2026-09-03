from fastapi.testclient import TestClient

from app.main import app


def test_healthz() -> None:
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_healthz_v1() -> None:
    client = TestClient(app)
    resp = client.get("/api/v1/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

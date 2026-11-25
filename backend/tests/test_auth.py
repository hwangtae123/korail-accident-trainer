"""비밀번호 잠금 (ACCESS_PASSWORD)."""
import pytest
from fastapi.testclient import TestClient

import tests.test_flow  # noqa: F401  (DATA_DIR를 임시 폴더로 — app을 import하기 전에)
from app.main import app


@pytest.fixture()
def locked(monkeypatch):
    monkeypatch.setenv("ACCESS_PASSWORD", "test-pw")
    return TestClient(app)


def test_no_password_means_open(monkeypatch):
    monkeypatch.setenv("ACCESS_PASSWORD", "")
    c = TestClient(app)
    assert c.get("/api/reports").status_code == 200
    assert c.get("/api/session").json() == {"required": False, "ok": True}


def test_locked_api_needs_login(locked):
    assert locked.get("/api/reports").status_code == 401
    assert locked.get("/api/health").status_code == 200  # 열어 둔 경로
    assert locked.get("/api/session").json() == {"required": True, "ok": False}


def test_wrong_password_rejected(locked):
    r = locked.post("/api/login", json={"password": "nope"})
    assert r.status_code == 401
    assert locked.get("/api/reports").status_code == 401


def test_login_then_logout(locked):
    assert locked.post("/api/login", json={"password": "test-pw"}).status_code == 200
    assert locked.get("/api/reports").status_code == 200
    assert locked.get("/api/session").json()["ok"] is True
    locked.post("/api/logout")
    assert locked.get("/api/reports").status_code == 401


def test_login_not_in_contract():
    paths = app.openapi()["paths"]
    assert not any(p in paths for p in ("/api/login", "/api/logout", "/api/session"))

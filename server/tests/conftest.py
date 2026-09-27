"""Shared fixtures for the auth/admin/usage tests: a fresh, isolated
database (fresh DATA_DIR + seeded admin) and, where wanted, a TestClient
already logged in as admin. test_jobs.py keeps its own richer fixture
(worker stubs included)."""
import pytest

from server.app import auth as auth_mod
from server.app import db as db_mod
from server.app.config import settings as _settings


@pytest.fixture()
def db_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    # Pin the seeded admin so the real .env (a user's live account) can't
    # change who/what these tests log in as.
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("REQUIRE_APPROVAL", "false")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    _settings.cache_clear()
    db_mod._jobs = None
    auth_mod.bootstrap()
    yield db_mod.get_db()
    db_mod._jobs = None
    _settings.cache_clear()


@pytest.fixture()
def client(db_reset):
    from fastapi.testclient import TestClient

    from server.app.main import app

    client = TestClient(app)
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text  # seeded by bootstrap, password from env
    return client

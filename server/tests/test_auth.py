"""Auth endpoints: admin seeding, signup (active vs pending), login, /me."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _fresh_client():
    """A browser with no cookies (or just alice's, once logged in)."""
    from fastapi.testclient import TestClient

    from server.app.main import app

    return TestClient(app)


def test_admin_seeded_from_env(db_reset):
    from server.app.db import get_db

    admin = get_db().get_user("admin")
    assert admin is not None
    assert admin["is_admin"] == 1
    assert admin["status"] == "active"


def test_login_bad_password_401(db_reset):
    r = _fresh_client().post(
        "/api/auth/login", json={"username": "admin", "password": "nope"}
    )
    assert r.status_code == 401


def test_me_requires_auth(client, db_reset):
    r = _fresh_client().get("/api/auth/me")
    assert r.status_code == 401
    # and the logged-in admin passes
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["username"] == "admin"
    assert r.json()["is_admin"] is True


def test_signup_auto_active_sets_cookie(client, db_reset):
    c = _fresh_client()
    r = c.post(
        "/api/auth/signup", json={"username": "alice", "password": "password123"}
    )
    assert r.status_code == 201, r.text
    assert r.json() == {"username": "alice", "pending": False}
    # signed up straight into a session (REQUIRE_APPROVAL is off)
    r = c.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["username"] == "alice"
    assert r.json()["is_admin"] is False


def test_signup_pending_when_approval_required(client, db_reset):
    db_reset.set_setting("require_approval", "1")
    c = _fresh_client()
    r = c.post(
        "/api/auth/signup", json={"username": "bob", "password": "password123"}
    )
    assert r.status_code == 201, r.text
    assert r.json()["pending"] is True
    # no session yet, and login is gated until an admin approves
    assert c.get("/api/auth/me").status_code == 401
    r = c.post(
        "/api/auth/login", json={"username": "bob", "password": "password123"}
    )
    assert r.status_code == 403, r.text

    # admin approves -> bob can log in
    r = client.patch(
        "/api/admin/users/bob", json={"status": "active"}
    )
    assert r.status_code == 200, r.text
    r = c.post(
        "/api/auth/login", json={"username": "bob", "password": "password123"}
    )
    assert r.status_code == 200, r.text
    assert c.get("/api/auth/me").json()["username"] == "bob"


def test_signup_duplicate_409(client, db_reset):
    c = _fresh_client()
    r = c.post(
        "/api/auth/signup", json={"username": "carol", "password": "password123"}
    )
    assert r.status_code == 201, r.text
    # case-insensitive unique: CAROL is carol
    r = c.post(
        "/api/auth/signup", json={"username": "CAROL", "password": "password123"}
    )
    assert r.status_code == 409


def test_signup_validation_422(client, db_reset):
    c = _fresh_client()
    r = c.post("/api/auth/signup", json={"username": "ab", "password": "password123"})
    assert r.status_code == 422
    r = c.post(
        "/api/auth/signup", json={"username": "valid-name", "password": "short"}
    )
    assert r.status_code == 422

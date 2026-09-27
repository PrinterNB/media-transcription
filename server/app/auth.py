"""User accounts + session cookies.

No routes here — just password hashing, signed session tokens, the
``require_user`` / ``require_admin`` FastAPI dependencies, and the idempotent
``bootstrap()`` (seed admin, persist settings, backfill job ownership) that
both the app lifespan and the tests call before serving requests.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

import argon2
from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .config import settings

COOKIE_NAME = "session"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days

_hasher = argon2.PasswordHasher()


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def verify_password(hashed: str, pw: str) -> bool:
    try:
        return _hasher.verify(hashed, pw)
    except (argon2.exceptions.VerificationError, argon2.exceptions.InvalidHashError):
        return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_session_token(username: str, secret: str) -> str:
    return URLSafeTimedSerializer(secret).dumps(username)


def read_session_token(secret: str, value: str) -> str | None:
    """Return the username a token names, or None if bad/expired/absent."""
    try:
        username = URLSafeTimedSerializer(secret).loads(
            value, max_age=COOKIE_MAX_AGE
        )
    except BadSignature:  # covers SignatureExpired / BadData / tampering
        return None
    return username if isinstance(username, str) and username else None


def get_secret() -> str:
    """Session-signing secret: env, else the persisted app_settings value."""
    s = settings()
    if s.session_secret:
        return s.session_secret
    from .db import get_db  # lazy: db imports settings, auth is imported by routes

    db = get_db()
    secret = db.get_setting("session_secret")
    if secret:
        return secret
    secret = secrets.token_hex(32)
    db.set_setting("session_secret", secret)
    return secret


def bootstrap() -> None:
    """Idempotent first-boot setup. Safe to call from lifespan AND tests."""
    from .db import get_db

    db = get_db()
    s = settings()

    admin = db.get_user(s.admin_username)
    if admin is None:
        # .env only fixes the password at CREATION; a later panel password
        # change must survive restarts.
        db.create_user(s.admin_username, hash_password(s.admin_password), True, "active")
    elif admin["is_admin"] != 1:
        db.set_user(s.admin_username, is_admin=True)

    if db.get_setting("require_approval") is None:
        db.set_setting("require_approval", "1" if s.require_approval else "0")

    db.backfill_job_owner(s.admin_username)


def require_user(request: Request) -> dict:
    """Return the logged-in user's row, or 401. The request carries a
    first-party `session` cookie with a signed username; the user must still
    exist and be active (a logout/deleted/disabled account fails here)."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "authentication required")
    username = read_session_token(get_secret(), token)
    if not username:
        raise HTTPException(401, "authentication required")
    from .db import get_db

    user = get_db().get_user(username)
    if not user or user["status"] != "active":
        raise HTTPException(401, "authentication required")
    return user


def require_admin(user: dict = Depends(require_user)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(403, "admin only")
    return user


def cookie_attrs() -> dict:
    """Kwargs for Response.set_cookie — HttpOnly, Lax, 30d; no Secure
    because this is a plain-HTTP LAN app."""
    return dict(
        httponly=True,
        samesite="lax",
        path="/",
        max_age=COOKIE_MAX_AGE,
    )

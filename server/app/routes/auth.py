"""POST /api/auth/login | /signup | /logout, GET /api/auth/me."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response

from .. import auth
from ..auth import COOKIE_NAME, cookie_attrs, require_user
from ..config import settings
from ..db import get_db

router = APIRouter(prefix="/api/auth")

_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")


def _require_approval() -> bool:
    """Effective approval gate: the persisted setting, else the env default."""
    v = get_db().get_setting("require_approval")
    if v is None:
        return settings().require_approval
    return v.strip() == "1"


@router.post("/login")
def login(body: dict | None = None, response: Response = None):
    username = str((body or {}).get("username") or "").strip()
    password = str((body or {}).get("password") or "")
    if not username or not password:
        raise HTTPException(422, "username and password are required")
    user = get_db().get_user(username)
    if not user or not auth.verify_password(user["password_hash"], password):
        raise HTTPException(401, "bad username or password")
    if user["status"] == "pending":
        raise HTTPException(403, "account awaiting approval")
    if user["status"] != "active":
        raise HTTPException(403, "account disabled")
    get_db().set_user(
        user["username"],
        last_login_at=datetime.now(timezone.utc).isoformat(),
    )
    token = auth.make_session_token(user["username"], auth.get_secret())
    response.set_cookie(COOKIE_NAME, token, **cookie_attrs())
    return {"username": user["username"], "is_admin": bool(user["is_admin"])}


@router.post("/signup", status_code=201)
def signup(body: dict | None = None, response: Response = None):
    username = str((body or {}).get("username") or "").strip()
    password = str((body or {}).get("password") or "")
    if not _USERNAME_RE.match(username):
        raise HTTPException(
            422, "username must be 3-32 chars (letters, digits, '.', '_', '-')"
        )
    if len(password) < 8:
        raise HTTPException(422, "password must be at least 8 characters")
    db = get_db()
    if db.get_user(username):
        raise HTTPException(409, "username already taken")

    pending = _require_approval()
    db.create_user(
        username, auth.hash_password(password), False,
        "pending" if pending else "active",
    )
    if not pending:
        # logged straight in — same cookie as login
        user = db.get_user(username)
        token = auth.make_session_token(user["username"], auth.get_secret())
        response.set_cookie(COOKIE_NAME, token, **cookie_attrs())
    return {"username": username, "pending": pending}


@router.post("/logout")
def logout(response: Response = None):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(require_user)):
    return {
        "username": user["username"],
        "is_admin": bool(user["is_admin"]),
        "status": user["status"],
        "created_at": user["created_at"],
        "last_login_at": user["last_login_at"],
    }

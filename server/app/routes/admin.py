"""Admin endpoints (/api/admin, all require_admin): users, all jobs, usage."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import auth
from ..auth import require_admin
from ..db import get_db
from ..pipeline.worker import TERMINAL
from .auth import _USERNAME_RE, _require_approval
from .jobs import _remove_job_files

router = APIRouter(prefix="/api/admin")


def _public(user: dict) -> dict:
    u = dict(user)
    u.pop("password_hash", None)
    return u


@router.get("/users")
def list_users(_: dict = Depends(require_admin)):
    return [_public(u) for u in get_db().list_users()]


@router.post("/users", status_code=201)
def create_user(body: dict | None = None, _: dict = Depends(require_admin)):
    """Provision a user — always ACTIVE immediately (bypasses approval)."""
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
    db.create_user(
        username, auth.hash_password(password),
        bool((body or {}).get("is_admin", False)), "active",
    )
    return _public(db.get_user(username))


@router.patch("/users/{username}")
def patch_user(
    username: str, body: dict | None = None, _: dict = Depends(require_admin)
):
    db = get_db()
    if not db.get_user(username):
        raise HTTPException(404, "no such user")
    body = body or {}
    kwargs: dict = {}
    if "is_admin" in body:
        kwargs["is_admin"] = bool(body["is_admin"])
    if "status" in body:
        status = str(body["status"]).strip()
        if status not in ("active", "pending", "disabled"):
            raise HTTPException(422, "status must be active, pending, or disabled")
        kwargs["status"] = status
    if "password" in body:
        password = str(body["password"] or "")
        if len(password) < 8:
            raise HTTPException(422, "password must be at least 8 characters")
        kwargs["password_hash"] = auth.hash_password(password)
    if not kwargs:
        raise HTTPException(422, "nothing to update")
    db.set_user(username, **kwargs)
    return _public(db.get_user(username))


@router.delete("/users/{username}")
def delete_user(username: str, actor: dict = Depends(require_admin)):
    db = get_db()
    target = db.get_user(username)
    if not target:
        raise HTTPException(404, "no such user")
    if target["username"] == actor["username"]:
        raise HTTPException(409, "you can't delete the account you're using")
    jobs = db.list(owner=username)
    if any(j["status"] not in TERMINAL for j in jobs):
        raise HTTPException(409, "that account has a job still running")
    for j in jobs:
        _remove_job_files(j["id"])
    db.delete_jobs_by_owner(username)
    db.delete_user(username)
    return {"deleted_user": username, "deleted_jobs": len(jobs)}


@router.get("/jobs")
def all_jobs(_: dict = Depends(require_admin)):
    return get_db().list()


@router.get("/usage")
def usage(_: dict = Depends(require_admin)):
    db = get_db()
    stats = db.job_stats_by_owner()
    users = []
    for u in db.list_users():
        s = stats.get(u["username"], {})
        users.append(
            {
                "username": u["username"],
                "is_admin": bool(u["is_admin"]),
                "jobs": s.get("jobs", 0),
                "bytes": s.get("bytes", 0),
                "prompt_tokens": s.get("prompt_tokens", 0),
                "completion_tokens": s.get("completion_tokens", 0),
                "duration_sec": s.get("duration_sec", 0),
            }
        )
    return {"users": users, "totals": db.job_stats_totals()}


@router.get("/settings")
def get_settings(_: dict = Depends(require_admin)):
    return {"require_approval": _require_approval()}


@router.put("/settings")
def put_settings(body: dict | None = None, _: dict = Depends(require_admin)):
    if not isinstance(body, dict) or not isinstance(
        body.get("require_approval"), bool
    ):
        raise HTTPException(422, "require_approval (boolean) is required")
    get_db().set_setting(
        "require_approval", "1" if body["require_approval"] else "0"
    )
    return {"require_approval": body["require_approval"]}

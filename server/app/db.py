"""sqlite3 job store. No ORM — a few explicit queries.

One row per job. Large/structured fields (options, speaker_map, segments) are
stored as JSON text and decoded on read. A single connection is used
per-call (check_same_thread=False + a lock) since the app is a single process
serving one worker.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import settings

# Sentinel for update(): distinguishes "not provided" from an explicit None
# (which must write SQL NULL, e.g. clearing pending_summary).
_UNSET = object()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Jobs:
    def __init__(self, db_path: Path) -> None:
        self._path = str(db_path)
        self._lock = threading.Lock()
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    source_name TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    message TEXT,
                    error TEXT,
                    options TEXT NOT NULL,
                    detected_language TEXT,
                    speaker_map TEXT,
                    segments TEXT,
                    output_paths TEXT,
                    summaries TEXT,
                    pending_summary TEXT,
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                )
                """
            )
            # Migrate older databases: add any column missing from the schema.
            cols = {
                r["name"] for r in c.execute("PRAGMA table_info(jobs)")
            }
            extra_cols = {
                "summaries": "TEXT",
                "pending_summary": "TEXT",
                "owner": "TEXT",
                "prompt_tokens": "INTEGER NOT NULL DEFAULT 0",
                "completion_tokens": "INTEGER NOT NULL DEFAULT 0",
                "duration_sec": "REAL",
            }
            for col, coltype in extra_cols.items():
                if col not in cols:
                    c.execute(f"ALTER TABLE jobs ADD COLUMN {col} {coltype}")
            c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_owner ON jobs (owner)")
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    last_login_at TEXT
                )
                """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

    # ---- create / read ----
    def create(
        self,
        source_name: str,
        size_bytes: int,
        options: dict,
        pending_summary: str | None = None,
        owner: str | None = None,
    ) -> dict:
        job_id = uuid.uuid4().hex
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO jobs (id, source_name, size_bytes, status, stage,"
                " progress, message, options, pending_summary, owner, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    source_name,
                    size_bytes,
                    "queued",
                    "queued",
                    0,
                    "queued",
                    json.dumps(options),
                    pending_summary,
                    owner,
                    _now(),
                ),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> dict | None:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT * FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
        return self._row(row) if row else None

    def list(self, owner: str | None = None) -> list[dict]:
        with self._lock, self._conn() as c:
            if owner is None:
                rows = c.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC"
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM jobs WHERE owner=? ORDER BY created_at DESC",
                    (owner,),
                ).fetchall()
        return [self._row(r) for r in rows]

    def delete_all(self) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM jobs")
            return cur.rowcount

    def delete_job(self, job_id: str) -> bool:
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            return cur.rowcount > 0

    def delete_jobs_by_owner(self, owner: str) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM jobs WHERE owner=?", (owner,))
            return cur.rowcount

    def _row(self, r: sqlite3.Row) -> dict:
        d = dict(r)
        for key in ("options", "speaker_map", "segments", "output_paths", "summaries"):
            raw = d.get(key)
            d[key] = json.loads(raw) if raw else (d.get(key))
        return d

    # ---- updates ----
    def update(
        self,
        job_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        progress: int | None = None,
        message: str | None = None,
        size_bytes: int | None = None,
        error: str | None = None,
        detected_language: str | None = None,
        speaker_map: dict | None = None,
        segments: list | None = None,
        output_paths: dict | None = None,
        summaries: dict | None = None,
        pending_summary: str | None = _UNSET,
        duration_sec: float | None = None,
        finished: bool = False,
    ) -> None:
        fields: list[str] = []
        args: list[Any] = []
        if status is not None:
            fields.append("status=?"); args.append(status)
        if stage is not None:
            fields.append("stage=?"); args.append(stage)
        if progress is not None:
            fields.append("progress=?"); args.append(int(progress))
        if message is not None:
            fields.append("message=?"); args.append(message)
        if size_bytes is not None:
            fields.append("size_bytes=?"); args.append(int(size_bytes))
        if error is not None:
            fields.append("error=?"); args.append(error)
        if detected_language is not None:
            fields.append("detected_language=?"); args.append(detected_language)
        if speaker_map is not None:
            fields.append("speaker_map=?"); args.append(json.dumps(speaker_map))
        if segments is not None:
            fields.append("segments=?"); args.append(json.dumps(segments))
        if output_paths is not None:
            fields.append("output_paths=?"); args.append(json.dumps(output_paths))
        if summaries is not None:
            fields.append("summaries=?"); args.append(json.dumps(summaries))
        if pending_summary is not _UNSET:
            fields.append("pending_summary=?"); args.append(pending_summary)
        if duration_sec is not None:
            fields.append("duration_sec=?"); args.append(float(duration_sec))
        if finished:
            fields.append("finished_at=?"); args.append(_now())
        if not fields:
            return
        args.append(job_id)
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id=?", args)

    def add_usage(self, job_id: str, prompt: int, completion: int) -> None:
        """Atomically add Ollama token usage to a job's counters."""
        with self._lock, self._conn() as c:
            c.execute(
                "UPDATE jobs SET prompt_tokens = prompt_tokens + ?,"
                " completion_tokens = completion_tokens + ? WHERE id=?",
                (int(prompt), int(completion), job_id),
            )

    def backfill_job_owner(self, owner: str) -> int:
        """Assign `owner` to jobs with no owner yet (pre-auth rows)."""
        with self._lock, self._conn() as c:
            cur = c.execute(
                "UPDATE jobs SET owner=? WHERE owner IS NULL", (owner,)
            )
            return cur.rowcount

    # ---- users (single-store convenience; same lock/connection pattern) ----
    def create_user(
        self, username: str, password_hash: str, is_admin: bool, status: str
    ) -> dict:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO users (id, username, password_hash, is_admin,"
                " status, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (
                    uuid.uuid4().hex,
                    username,
                    password_hash,
                    1 if is_admin else 0,
                    status,
                    _now(),
                ),
            )
        return self.get_user(username)

    def get_user(self, username: str) -> dict | None:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT * FROM users WHERE username=?", (username,)
            ).fetchone()
        return dict(row) if row else None

    def list_users(self) -> list[dict]:
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT * FROM users ORDER BY username").fetchall()
        stats = self.job_stats_by_owner()
        out = []
        for r in rows:
            d = dict(r)
            s = stats.get(r["username"]) or {}
            d["job_count"] = s.get("jobs", 0)
            d["bytes"] = s.get("bytes", 0)
            d["prompt_tokens"] = s.get("prompt_tokens", 0)
            d["completion_tokens"] = s.get("completion_tokens", 0)
            out.append(d)
        return out

    def set_user(
        self,
        username: str,
        *,
        is_admin: bool | None = None,
        status: str | None = None,
        password_hash: str | None = None,
        last_login_at: str | None = None,
    ) -> int:
        fields: list[str] = []
        args: list[Any] = []
        if is_admin is not None:
            fields.append("is_admin=?"); args.append(1 if is_admin else 0)
        if status is not None:
            fields.append("status=?"); args.append(status)
        if password_hash is not None:
            fields.append("password_hash=?"); args.append(password_hash)
        if last_login_at is not None:
            fields.append("last_login_at=?"); args.append(last_login_at)
        if not fields:
            return 0
        args.append(username)
        with self._lock, self._conn() as c:
            cur = c.execute(
                f"UPDATE users SET {', '.join(fields)} WHERE username=?", args
            )
            return cur.rowcount

    def delete_user(self, username: str) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM users WHERE username=?", (username,))
            return cur.rowcount

    # ---- app_settings (key/value bootstrap flags, e.g. session secret) ----
    def get_setting(self, key: str) -> str | None:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT value FROM app_settings WHERE key=?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO app_settings (key, value) VALUES (?,?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    # ---- per-user stats (admin) ----
    def job_stats_by_owner(self) -> dict[str, dict]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT owner, COUNT(*) AS jobs, COALESCE(SUM(size_bytes),0) AS bytes,"
                " COALESCE(SUM(prompt_tokens),0) AS prompt_tokens,"
                " COALESCE(SUM(completion_tokens),0) AS completion_tokens,"
                " COALESCE(SUM(duration_sec),0) AS duration_sec"
                " FROM jobs GROUP BY owner"
            ).fetchall()
        return {
            r["owner"]: {
                "jobs": r["jobs"],
                "bytes": r["bytes"],
                "prompt_tokens": r["prompt_tokens"],
                "completion_tokens": r["completion_tokens"],
                "duration_sec": r["duration_sec"],
            }
            for r in rows
        }

    def job_stats_totals(self) -> dict:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS jobs, COALESCE(SUM(size_bytes),0) AS bytes,"
                " COALESCE(SUM(prompt_tokens),0) AS prompt_tokens,"
                " COALESCE(SUM(completion_tokens),0) AS completion_tokens,"
                " COALESCE(SUM(duration_sec),0) AS duration_sec FROM jobs"
            ).fetchone()
        return {
            "jobs": row["jobs"],
            "bytes": row["bytes"],
            "prompt_tokens": row["prompt_tokens"],
            "completion_tokens": row["completion_tokens"],
            "duration_sec": row["duration_sec"],
        }


_jobs: Jobs | None = None


def get_db() -> Jobs:
    global _jobs
    if _jobs is None:
        _jobs = Jobs(settings().db_path)
    return _jobs

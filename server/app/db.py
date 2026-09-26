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
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                )
                """
            )

    # ---- create / read ----
    def create(self, source_name: str, size_bytes: int, options: dict) -> dict:
        job_id = uuid.uuid4().hex
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO jobs (id, source_name, size_bytes, status, stage,"
                " progress, message, options, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    source_name,
                    size_bytes,
                    "queued",
                    "queued",
                    0,
                    "queued",
                    json.dumps(options),
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

    def list(self) -> list[dict]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC"
            ).fetchall()
        return [self._row(r) for r in rows]

    def delete_all(self) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM jobs")
            return cur.rowcount

    def _row(self, r: sqlite3.Row) -> dict:
        d = dict(r)
        for key in ("options", "speaker_map", "segments", "output_paths"):
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
        if finished:
            fields.append("finished_at=?"); args.append(_now())
        if not fields:
            return
        args.append(job_id)
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id=?", args)


_jobs: Jobs | None = None


def get_db() -> Jobs:
    global _jobs
    if _jobs is None:
        _jobs = Jobs(settings().db_path)
    return _jobs

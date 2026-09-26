"""GET /api/jobs, /{id}, /{id}/events (SSE), POST /{id}/cancel."""
from __future__ import annotations

import shutil
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..config import settings
from ..db import get_db
from ..pipeline.worker import get_worker, TERMINAL

router = APIRouter(prefix="/api")


@router.get("/jobs")
async def list_jobs():
    return get_db().list()


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = get_db().get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    return job


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str):
    if not get_db().get(job_id):
        raise HTTPException(404, "no such job")

    def snapshot() -> dict:
        j = get_db().get(job_id)
        return j if j else {"status": "error", "stage": "error", "error": "vanished"}

    async def gen() -> AsyncIterator[bytes]:
        from .. import sse
        async for event, data in sse.stream_job(snapshot):
            yield f"event: {event}\ndata: {data}\n\n".encode("utf-8")

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.delete("/jobs")
async def clear_jobs():
    """Clear job history and delete all uploads/outputs on disk."""
    db = get_db()
    s = settings()
    if any(j["status"] not in TERMINAL for j in db.list()):
        raise HTTPException(409, "a job is still running — cancel it first")
    for d in (s.uploads_dir, s.outputs_dir):
        if d.is_dir():
            for child in d.iterdir():
                shutil.rmtree(child) if child.is_dir() else child.unlink(missing_ok=True)
    deleted = db.delete_all()
    return {"deleted_jobs": deleted}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    db = get_db()
    job = db.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    if job["status"] in TERMINAL:
        return job  # already finished; nothing to cancel
    get_worker().request_cancel(job_id)
    return db.get(job_id)

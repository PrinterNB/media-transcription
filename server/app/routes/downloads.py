"""GET /api/jobs/{id}/download?fmt=txt|srt|vtt|json — serve a finished output."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..auth import require_user
from ..db import get_db
from .jobs import _get_job_for

router = APIRouter(prefix="/api")

_EXT = {"txt": "txt", "srt": "srt", "vtt": "vtt", "json": "json"}
_MEDIA = {
    "txt": "text/plain; charset=utf-8",
    "srt": "application/x-subrip; charset=utf-8",
    "vtt": "text/vtt; charset=utf-8",
    "json": "application/json; charset=utf-8",
}


@router.get("/jobs/{job_id}/download")
async def download(job_id: str, fmt: str = "txt", user: dict = Depends(require_user)):
    fmt = (fmt or "txt").lower()
    if fmt not in _EXT:
        raise HTTPException(422, "fmt must be one of: txt, srt, vtt, json")
    job = _get_job_for(job_id, user)
    if job["status"] != "done":
        raise HTTPException(409, "job not finished yet")
    paths = job.get("output_paths") or {}
    path = paths.get(fmt)
    if not path or not Path(path).exists():
        raise HTTPException(404, f"{fmt} output missing on disk")
    filename = f"{Path(path).stem}.{_EXT[fmt]}"
    return FileResponse(
        path, media_type=_MEDIA[fmt], filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

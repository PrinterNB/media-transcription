"""POST /api/jobs — multipart upload creating a transcription job."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pathlib import Path

from ..config import settings
from ..db import get_db
from ..pipeline import audio, summarize
from ..pipeline.worker import get_worker

router = APIRouter(prefix="/api")


def _b(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _safe_name(name: str) -> str:
    # keep the original basename, avoid path traversal
    return Path(name).name or "upload.bin"


def _mark_error(job_id: str, msg: str) -> None:
    # A 422 raised after the job row exists means the worker never got the
    # job — mark it errored so it doesn't sit in "queued" forever.
    get_db().update(
        job_id, status="error", stage="error", error=msg, message=msg,
        finished=True,
    )


@router.post("/jobs", status_code=202)
async def create_job(
    file: UploadFile = File(...),
    asr: str = Form("canary"),
    language_hint: str | None = Form(None),
    extracted: str = Form("false"),
    diarize: str = Form("true"),
    naming: str = Form("true"),
    ollama_model: str | None = Form(None),
    summary_template: str | None = Form(None),
):
    asr = (asr or "canary").strip()
    if asr not in ("canary", "whisper"):
        raise HTTPException(422, "asr must be 'canary' or 'whisper'")
    is_extracted = _b(extracted)

    # Optional summary to run as soon as transcription finishes (the worker
    # picks it up from pending_summary). Blank = decide later from the UI.
    summary_template = (summary_template or "").strip() or None
    if summary_template and not summarize.get_template(summary_template):
        raise HTTPException(400, f"unknown summary template: {summary_template}")

    db = get_db()
    job = db.create(
        source_name=_safe_name(file.filename or "upload.bin"),
        size_bytes=0,
        options={
            "asr": asr,
            "language_hint": (language_hint or "").strip() or None,
            "extracted": is_extracted,
            "diarize": _b(diarize),
            "naming": _b(naming),
            "ollama_model": (ollama_model or "").strip() or None,
            "summary_template": summary_template,
        },
        pending_summary=summary_template,
    )
    job_id = job["id"]
    job_dir = settings().uploads_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    dest = job_dir / job["source_name"]

    # spool the upload to disk
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)

    if not dest.exists() or dest.stat().st_size == 0:
        msg = "Uploaded file was empty."
        _mark_error(job_id, msg)
        raise HTTPException(422, msg)
    db.update(job_id, size_bytes=dest.stat().st_size)

    # If the browser claims it already sent a clean 16 kHz mono WAV, verify it.
    if is_extracted:
        try:
            props = audio.probe_props(dest)
        except audio.AudioError as e:
            msg = f"Could not read uploaded audio: {e}"
            _mark_error(job_id, msg)
            raise HTTPException(422, msg)
        if props.get("sample_rate") != 16000 or props.get("channels") != 1:
            msg = (
                f"extracted=true but audio is {props.get('sample_rate')}Hz/"
                f"{props.get('channels')}ch; expected 16000Hz mono. "
                "Re-upload without client extraction."
            )
            _mark_error(job_id, msg)
            raise HTTPException(422, msg)

    get_worker().submit(job_id)
    return job


@router.get("/ollama/models")
async def ollama_models():
    """Installed Ollama models (for the naming-stage model picker).

    Footer/debug use — never 5xx: if Ollama is down we return the empty list
    with an error message and the UI degrades to the default.
    """
    s = settings()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(2.0)) as client:
            r = await client.get(s.ollama_url + "/api/tags")
            r.raise_for_status()
            tags = r.json()
        names = sorted(
            m.get("name", "") for m in tags.get("models", []) if m.get("name")
        )
        return {"models": names}
    except Exception as e:  # noqa: BLE001
        return {"models": [], "error": str(e) or type(e).__name__}


@router.get("/health")
async def health():
    from ..models.manager import get_manager

    s = settings()
    # non-fatal probes: ffmpeg on PATH, Ollama reachable
    import shutil
    import urllib.request, json as _json
    ollama_ok = False
    try:
        req = urllib.request.Request(s.ollama_url + "/api/tags")
        with urllib.request.urlopen(req, timeout=2) as r:
            r.read()
        ollama_ok = True
    except Exception:  # noqa: BLE001
        ollama_ok = False
    return {
        "ok": True,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ollama_reachable": ollama_ok,
        "ollama_url": s.ollama_url,
        "resident": get_manager().resident(),
    }

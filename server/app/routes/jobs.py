"""GET /api/jobs, /{id}, /{id}/events (SSE), POST /{id}/cancel, summarize, chat."""
from __future__ import annotations

import shutil
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..config import settings
from ..db import get_db
from ..models.manager import get_manager
from ..pipeline import naming, summarize
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


# ---- summaries + chat (Ollama) ----
# These are SYNC defs on purpose: the Ollama call blocks up to 600 s, and
# FastAPI runs sync routes in the threadpool, keeping the event loop (and the
# SSE streams of other jobs) free.
@router.get("/summary/templates")
async def summary_templates():
    return summarize.list_templates()


def _other_job_live() -> bool:
    return any(j["status"] in ("queued", "running") for j in get_db().list())


@router.post("/jobs/{job_id}/summarize")
def summarize_job(job_id: str, body: dict | None = None):
    """Run a summary template (or null to clear the pending selection)."""
    db = get_db()
    job = db.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")

    template = (body or {}).get("template")
    if template is not None:
        template = str(template or "").strip() or None

    if template is None:
        db.update(job_id, pending_summary=None)
        return {"cleared": True}

    if not summarize.get_template(template):
        raise HTTPException(400, f"unknown summary template: {template}")

    if job["status"] != "done":
        if job["status"] in ("queued", "running"):
            # The worker runs it right before marking the job done.
            db.update(job_id, pending_summary=template)
            return {"queued": True}
        raise HTTPException(400, "job did not finish with a transcript")

    if not (job.get("segments") or []):
        raise HTTPException(400, "job has no transcript segments to summarize")

    # Don't yank ASR out of VRAM from under a job that's mid-pipeline.
    if _other_job_live():
        raise HTTPException(409, "another job is still running — wait for it to finish, then run the summary")

    model = (job.get("options") or {}).get("ollama_model") or None
    get_manager().prepare_for_ollama()  # free ASR + diarizer BEFORE Ollama
    try:
        with naming.llm_session():  # frees resident Ollama models after
            result = summarize.run_template(job, template, model)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not (result or "").strip():
        raise HTTPException(502, "the summary model returned no output (is Ollama running?)")
    summaries = dict(job.get("summaries") or {})
    summaries[template] = result
    db.update(job_id, summaries=summaries)
    return {"summary": result}


@router.post("/jobs/{job_id}/chat")
def chat_with_transcript(job_id: str, body: dict | None = None):
    """Answer a question about a finished job's transcript."""
    db = get_db()
    job = db.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    if job["status"] != "done":
        raise HTTPException(400, "job is not finished yet")
    if not (job.get("segments") or []):
        raise HTTPException(400, "job has no transcript to chat with")

    body = body or {}
    message = str(body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message is required")

    history = [
        {"role": m["role"], "content": m["content"]}
        for m in (body.get("history") or [])
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)
    ][-10:]

    if _other_job_live():
        raise HTTPException(409, "another job is still running — wait for it to finish, then ask again")

    model = (job.get("options") or {}).get("ollama_model") or None
    get_manager().prepare_for_ollama()  # free ASR + diarizer BEFORE Ollama
    with naming.llm_session():  # frees resident Ollama models after
        reply = summarize.answer(job, message, history, model)
    if not (reply or "").strip():
        raise HTTPException(502, "the chat model returned no output (is Ollama running?)")
    return {"reply": reply}

"""Single background worker: the job stage machine.

One consumer thread processes jobs strictly one at a time, which (by
construction) guarantees the VRAM rule: stages run sequentially, and the
naming stage calls `manager.prepare_for_ollama()` — unloading ASR + the
diarizer — BEFORE it touches Ollama. Ollama and ASR/diarization therefore
never coexist in VRAM.

Stages (sequential):
    queued -> extracting -> transcribing -> diarizing -> naming -> writing
          -> done | error | cancelled

Stage progress is weighted; skipped stages (toggle off) just advance the
cursor, keeping progress monotonic.
"""
from __future__ import annotations

import logging
import queue as _queue
import threading
from pathlib import Path

from ..config import settings
from ..db import get_db
from ..models.manager import get_manager
from . import align, audio, naming, outputs, summarize

log = logging.getLogger(__name__)

# (stage_name, start_pct, end_pct)
BOUNDARIES = [
    ("extracting", 0, 5),
    ("transcribing", 5, 70),
    ("diarizing", 70, 85),
    ("naming", 85, 95),
    ("writing", 95, 100),
]
TERMINAL = ("done", "error", "cancelled")


class JobWorker:
    def __init__(self) -> None:
        self.q: _queue.Queue = _queue.Queue()
        self._thread: threading.Thread | None = None
        self._cancel: set[str] = set()

    # ---- lifecycle ----
    def start(self) -> None:
        self._resume_stale()
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="job-worker", daemon=True)
        self._thread.start()

    def _resume_stale(self) -> None:
        """Re-queue jobs a previous process left non-terminal (crash/restart).

        The queue is in-memory, so without this a job still marked `running`
        in sqlite would sit there forever after the server is restarted.
        """
        for job in get_db().list():
            if job["status"] not in TERMINAL:
                self.q.put(job["id"])

    def _loop(self) -> None:
        while True:
            job_id = self.q.get()
            try:
                self._run(job_id)
            except Exception:  # noqa: BLE001  (defence; _run handles its own)
                log.exception("worker unhandled error for %s", job_id)
            finally:
                self.q.task_done()

    def submit(self, job_id: str) -> None:
        self.q.put(job_id)

    def request_cancel(self, job_id: str) -> bool:
        """Return True if a queued/running job was flagged for cancel."""
        self._cancel.add(job_id)
        db = get_db()
        job = db.get(job_id)
        if job and job["status"] not in TERMINAL:
            return True
        return False

    def _cancelled(self, job_id: str) -> bool:
        return job_id in self._cancel

    # ---- progress helper factory ----
    def _reporter(self, job_id: str):
        db = get_db()

        def make_stage_reporter(stage: str):
            start = next(b[1] for b in BOUNDARIES if b[0] == stage)
            end = next(b[2] for b in BOUNDARIES if b[0] == stage)
            span = max(1, end - start)

            def cb(frac: float, msg: str = "") -> None:
                if self._cancelled(job_id):
                    return
                pct = int(start + min(1.0, max(0.0, frac)) * span)
                db.update(job_id, stage=stage, progress=pct, message=msg or stage)

            return cb

        return make_stage_reporter

    # ---- per-job run ----
    def _run(self, job_id: str) -> None:
        db = get_db()
        job = db.get(job_id)
        if not job:
            return
        s = settings()
        manager = get_manager()
        stage_report = self._reporter(job_id)

        job_dir = s.uploads_dir / job_id
        wav = job_dir / "audio_16k.wav"
        # the uploaded source: the route stores exactly one file in job_dir.
        # audio_16k.wav is a derived artifact of the extract stage (a previous
        # failed/cancelled run can leave one behind), so it must never be
        # mistaken for the upload — skip it explicitly for determinism.
        src = next(
            (p for p in sorted(job_dir.glob("*"))
             if p.is_file() and p.name != wav.name),
            None,
        )
        if src is None or not src.exists():
            self._fail(job_id, "No uploaded file found for this job.")
            return

        # Ollama keeps models warm between requests; unload any so they don't
        # sit in VRAM next to the ASR model (and free room for this job).
        naming.unload_all()

        opts = job.get("options", {}) or {}
        opts = _fill_defaults(opts)
        backend = opts.get("asr", s.asr_default)
        language = opts.get("language_hint") or None
        do_diarize = bool(opts.get("diarize", True))
        do_naming = bool(opts.get("naming", True))
        ollama_model = opts.get("ollama_model") or None  # None = server default

        try:
            # --- extracting (0-5) ---
            if self._cancelled(job_id):
                self._done_cancelled(job_id)
                return
            rep = stage_report("extracting")
            db.update(job_id, status="running", stage="extracting", progress=0, message="Extracting audio…")
            duration = audio.normalize(src, wav, lambda f, m="": rep(f, m))
            rep(1.0, "audio ready")

            # --- transcribing (5-70) ---
            if self._cancelled(job_id):
                self._done_cancelled(job_id)
                return
            db.update(job_id, stage="transcribing", progress=5, message="Transcribing…")
            rep = stage_report("transcribing")
            segments, detected = manager.transcribe(backend, str(wav), rep, language=language)
            detected_lang = detected or (language if backend == "whisper" else "en")
            db.update(job_id, detected_language=detected_lang, progress=70,
                      message=f"Transcribed ({len(segments)} segments)")

            # --- diarizing (70-85) ---
            speaker_map: dict = {}
            if do_diarize:
                if self._cancelled(job_id):
                    self._done_cancelled(job_id)
                    return
                db.update(job_id, stage="diarizing", progress=70, message="Diarizing…")
                tracks = manager.diarize(str(wav))
                segments = align.assign_and_merge(segments, tracks)
                rep = stage_report("diarizing")
                rep(1.0, f"{len({t.speaker for t in tracks})} speakers")
            else:
                db.update(job_id, stage="diarizing", progress=85,
                          message="Diarization skipped")

            # --- naming (85-95) ---
            if do_naming and do_diarize:
                if self._cancelled(job_id):
                    self._done_cancelled(job_id)
                    return
                db.update(job_id, stage="naming", progress=85, message="Naming speakers…")
                manager.prepare_for_ollama()  # free ASR + diarizer BEFORE Ollama
                rep = stage_report("naming")
                with naming.llm_session():  # frees resident Ollama models after
                    speaker_map = naming.infer_names(
                        segments, progress_cb=rep, model=ollama_model
                    )
            elif do_naming and not do_diarize:
                db.update(job_id, stage="naming", progress=95,
                          message="Naming skipped (diarization off)")
            else:
                # diarize on, naming off: expose anonymous Speaker N entries
                ids = [sp for sp in dict.fromkeys(x.speaker for x in segments) if sp]
                speaker_map = {sid: {"name": None, "confidence": 0.0, "evidence": ""}
                               for sid in ids}
                db.update(job_id, stage="naming", progress=95, message="Naming skipped")

            # --- writing (95-100) ---
            db.update(job_id, stage="writing", progress=95, message="Writing outputs…")
            rep = stage_report("writing")
            paths = outputs.write_all(
                s.outputs_dir, job_id, job["source_name"], duration,
                speaker_map, segments,
            )
            # Pending summary (picked in the UI while the job was running).
            # Fresh DB read: pending_summary may have been set after the row
            # loaded at the top of _run.
            pending = ((db.get(job_id) or {}).get("pending_summary") or "").strip() or None
            if pending and summarize.get_template(pending):
                if not self._cancelled(job_id):
                    db.update(job_id, message=f"Summarizing ({pending})…")
                    # Idempotent: a no-op if the naming stage already freed
                    # VRAM, required when naming was skipped for this job.
                    manager.prepare_for_ollama()
                    try:
                        with naming.llm_session():  # frees resident Ollama models after
                            text = summarize.run_template(
                                {"segments": segments, "speaker_map": speaker_map, "options": opts},
                                pending, model=ollama_model, progress_cb=rep,
                            )
                        if text:
                            stored = db.get(job_id) or {}
                            summaries = dict(stored.get("summaries") or {})
                            summaries[pending] = text
                            db.update(job_id, summaries=summaries)
                        else:
                            log.warning("summary for %s came back empty", job_id)
                    except Exception:  # noqa: BLE001
                        log.exception("auto summary failed for %s", job_id)
                db.update(job_id, pending_summary=None)
            rep(1.0, "done")
            db.update(
                job_id, status="done", stage="done", progress=100, message="Done",
                speaker_map=speaker_map, segments=[x.to_dict() for x in segments],
                output_paths=paths, finished=True,
            )
        except audio.AudioError as e:
            self._fail(job_id, f"Audio: {e}")
        except Exception as e:  # noqa: BLE001
            log.exception("job %s failed", job_id)
            self._fail(job_id, f"{type(e).__name__}: {e}")

    def _fail(self, job_id: str, msg: str) -> None:
        get_db().update(job_id, status="error", stage="error", error=msg,
                        message=msg, finished=True)

    def _done_cancelled(self, job_id: str) -> None:
        get_db().update(job_id, status="cancelled", stage="cancelled",
                        message="Cancelled", finished=True)


def _fill_defaults(opts: dict) -> dict:
    opts = dict(opts or {})
    opts.setdefault("asr", "canary")
    opts.setdefault("language_hint", None)
    opts.setdefault("diarize", True)
    opts.setdefault("naming", True)
    opts.setdefault("extracted", False)
    opts.setdefault("ollama_model", None)
    return opts


_worker: JobWorker | None = None


def get_worker() -> JobWorker:
    global _worker
    if _worker is None:
        _worker = JobWorker()
    return _worker

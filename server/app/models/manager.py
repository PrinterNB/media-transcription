"""Model manager — the VRAM heart.

Hard rule (from the user): the LLM (Ollama) must never run at the same time as
transcription or diarization. On 16 GB we can't hold canary (~6 GB) or whisper
(~3.1 GB) AND a 27B Ollama model (~13.7 GB) at once. So:

  * Exactly ONE ASR model is resident at a time (`_asr_slot`). Requesting a
    different backend unloads the current one first.
  * The pyannote diarizer lives in its own resident slot (`_diarize_slot`),
    kept warm across jobs (~1 GB) but unloaded before Ollama.
  * `prepare_for_ollama()` unloads ASR + diarizer and frees the cache BEFORE
    the naming stage calls Ollama. The worker calls this, then hits Ollama, so
    the two never overlap.

This is a process-wide singleton (one uvicorn worker).
"""
from __future__ import annotations

import gc
import logging
from typing import Optional

from ..config import settings
from .asr_base import ProgressCB, Segment
from .asr_canary import CanaryTranscriber
from .asr_whisper import WhisperTranscriber
from .diarize import Diarizer, DiarizationTrack, DiarizationError

log = logging.getLogger(__name__)


class ModelManager:
    def __init__(self) -> None:
        s = settings()
        self._canary = CanaryTranscriber(s.canary_model)
        self._whisper = WhisperTranscriber(s.whisper_model)
        self._diarizer = Diarizer(s.diarization_model, s.hf_token)
        self._active_asr: Optional[object] = None  # which of canary/whisper is resident

    # ---- ASR slot (one at a time) ----
    def get_asr(self, name: str):
        """Return a loaded Transcriber for `name` ('canary'|'whisper').

        If a different backend is resident, it is unloaded first so the two
        never coexist in VRAM.
        """
        backend = self._canary if name == "canary" else self._whisper
        if self._active_asr is backend:
            return backend
        self._unload_asr()
        backend.load()
        self._active_asr = backend
        return backend

    def _unload_asr(self) -> None:
        if self._active_asr is None:
            return
        current = self._active_asr
        self._active_asr = None
        current.unload()
        self._free()

    def _free(self) -> None:
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass

    def transcribe(self, backend: str, wav_path: str, progress_cb: ProgressCB | None,
                   language: str | None = None) -> tuple[list[Segment], str | None]:
        """Load the right ASR, transcribe, return (segments, detected_language).

        Does NOT unload afterwards — the caller decides (the worker keeps it
        for diarization only if needed, else unloads before Ollama).
        """
        asr = self.get_asr(backend)
        if backend == "whisper":
            segs = asr.transcribe(wav_path, progress_cb, language=language)
            detected = getattr(asr, "detected_language", None)
        else:
            segs = asr.transcribe(wav_path, progress_cb)
            detected = "en"
        return segs, detected

    # ---- diarizer slot ----
    def get_diarizer(self) -> Diarizer:
        return self._diarizer

    def diarize(self, wav_path: str) -> list[DiarizationTrack]:
        return self._diarizer.diarize(wav_path)

    # ---- the Ollama boundary ----
    def prepare_for_ollama(self) -> None:
        """Free every model we own before calling Ollama (the hard VRAM rule)."""
        self._unload_asr()
        if self._diarizer.is_loaded():
            self._diarizer.unload()
        self._free()

    def resident(self) -> dict:
        return {
            "asr": getattr(self._active_asr, "name", None),
            "canary_loaded": self._canary.is_loaded(),
            "whisper_loaded": self._whisper.is_loaded(),
            "diarizer_loaded": self._diarizer.is_loaded(),
        }


_manager: Optional[ModelManager] = None


def get_manager() -> ModelManager:
    global _manager
    if _manager is None:
        _manager = ModelManager()
    return _manager

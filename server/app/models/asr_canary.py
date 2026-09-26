"""Canary-qwen-2.5B ASR (English + accents only).

`nvidia/canary-qwen-2.5b` is a NeMo speech-LM (SALM), not a plain HF causal
LM — `AutoModelForCausalLM` rejects its DiaConfig (see docs/spike-notes.md).
So this backend loads it the documented way:

    from nemo.collections.speechlm2.models import SALM
    model = SALM.from_pretrained(...).bfloat16().eval().to("cuda")

and transcribes by passing the wav PATH to `model.generate()` inside a chat
prompt (`model.audio_locator_tag`), chunked into ~30 s windows so progress
stays granular and one window can't blow past max_new_tokens.

Word timestamps: SALM `generate()` returns token ids only; per the spike
notes per-word timestamps are unverified, so we emit the designed fallback —
sentence-level segments with empty `words`. Sentences get time bounds by
splitting each chunk's [start, end] span proportionally to character count
(deterministic; good enough for speaker alignment, which is segment-grained
anyway). Chunks are advanced window-by-window with NO overlap: SALM returns
plain text, so a 2 s overlap would duplicate transcript at the boundary with
no cheap way to de-dupe.

nemo/transformers are imported lazily inside load() so the app boots without
them importable at module load time.
"""
from __future__ import annotations

import gc
import os
import re

from ..config import local_model_dir
from .asr_base import ProgressCB, Segment

# 30s windows, no overlap (see module docstring). Long windows = fewer
# generate() round trips and better context for the LLM; 30s keeps progress
# granular on a 6 GB model.
_WINDOW = 30.0

# Sentence splitter: break after terminal punctuation (incl. newlines), keep
# deterministic, don't care about quoted abbreviations.
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _sentences(text: str) -> list[str]:
    """Split transcript text into sentences (non-empty, stripped)."""
    return [p.strip() for p in _SENT_SPLIT.split(text.strip()) if p.strip()]


class CanaryTranscriber:
    name = "canary"

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self._model = None

    # ---- lifecycle ----
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        try:
            from nemo.collections.speechlm2.models import SALM
        except ImportError as e:
            raise RuntimeError(
                "Canary requires the NeMo SALM loader but 'nemo' is not "
                f"importable in this venv: {e}"
            ) from e
        # Manual install (README, option B): models/canary-qwen-2.5b/
        # (config.json + model.safetensors) wins over the hub id — NeMo
        # resolves both from a local directory. (The small Qwen tokenizer
        # files still resolve via the hub; public, cached after first use.)
        source = str(local_model_dir("canary-qwen-2.5b") or self.model_id)
        try:
            self._model = (
                SALM.from_pretrained(source).bfloat16().eval().to("cuda")
            )
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                f"Failed to load Canary ({self.model_id}) via NeMo SALM: {e}"
            ) from e

    def unload(self) -> None:
        if self._model is None:
            return
        del self._model
        self._model = None
        gc.collect()
        import torch
        torch.cuda.empty_cache()

    # ---- inference ----
    def transcribe(self, wav_path: str, progress_cb: ProgressCB | None = None) -> list[Segment]:
        if self._model is None:
            raise RuntimeError("Canary not loaded; call load() first")
        import numpy as np
        import soundfile as sf
        import torch

        audio, sr = sf.read(wav_path, dtype="float32")
        if sr != 16000:
            raise ValueError(f"expected 16kHz wav, got {sr}Hz")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)

        total = len(audio) / 16000.0
        n_windows = max(1, int(np.ceil(total / _WINDOW)))

        chunks: list[tuple[float, float, str]] = []  # (start, end, text)
        for i in range(n_windows):
            start_s = i * _WINDOW
            end_s = min(start_s + _WINDOW, total)
            if start_s >= total:
                break
            a = int(start_s * 16000)
            b = min(int(end_s * 16000), len(audio))
            chunk = audio[a:b]
            if chunk.size == 0:
                break

            text = self._transcribe_chunk(wav_path, i, chunk)
            chunks.append((start_s, end_s, text))

            if progress_cb:
                progress_cb(min(1.0, (i + 1) / n_windows),
                            f"canary window {i+1}/{n_windows}")

        # Sentence-level segments with empty `words` (SALM returns ids only —
        # see module docstring for why word timestamps are the fallback).
        segments: list[Segment] = []
        for start_s, end_s, text in chunks:
            segments.extend(self._chunk_segments(start_s, end_s, text))
        return segments

    def _transcribe_chunk(self, wav_path: str, i: int, chunk: np.ndarray) -> str:
        """Write `chunk` to a temp .wav in the input's dir and run one SALM
        generate() over it. Sequential, one window per call — safest with a
        6 GB model resident (batch=1, no prompt stacking)."""
        import soundfile as sf
        import torch

        model = self._model
        chunk_path = os.path.join(
            os.path.dirname(os.path.abspath(wav_path)),
            f".canary_chunk_{i}_{os.getpid()}.wav",
        )
        sf.write(chunk_path, chunk, 16000, subtype="PCM_16")
        try:
            try:
                with torch.inference_mode():
                    answer_ids = model.generate(
                        prompts=[[{"role": "user",
                                   "content": f"Transcribe the following: {model.audio_locator_tag}",
                                   "audio": [chunk_path]}]],
                        max_new_tokens=128,
                    )
                return model.tokenizer.ids_to_text(answer_ids[0].cpu()).strip()
            except Exception:
                # A single bad window (silence oddities etc.) shouldn't kill
                # the whole job — emit nothing for it and keep going.
                return ""
        finally:
            try:
                os.remove(chunk_path)
            except OSError:
                pass

    @staticmethod
    def _chunk_segments(start_s: float, end_s: float, text: str) -> list[Segment]:
        """Split one chunk's transcript into sentence segments, distributing
        the chunk's [start, end] time span across sentences proportionally to
        character count. Simple and deterministic; coverage of the full audio
        duration holds because windows tile the file (empty-text chunks —
        silence — just contribute nothing)."""
        text = text.strip()
        if not text:
            return []
        sentences = _sentences(text)
        if not sentences:
            return []
        total_chars = sum(len(s) for s in sentences) or 1
        out: list[Segment] = []
        t = start_s
        for s in sentences:
            t1 = t + (end_s - start_s) * (len(s) / total_chars)
            out.append(Segment(start=t, end=t1, text=s))
            t = t1
        return out

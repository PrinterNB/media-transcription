"""Whisper large-v3 ASR via faster-whisper (all languages).

Multilingual fallback for the "not only English" option. Uses the lazy
segment generator so long files don't blow up RAM, and VAD filtering for
robust long-form behavior. `info.language` is surfaced so the UI/DB can show
the detected language.
"""
from __future__ import annotations

from .asr_base import ProgressCB, Segment, Word


class WhisperTranscriber:
    name = "whisper"

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self._model = None
        self.detected_language: str | None = None

    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        self._model = WhisperModel(self.model_id, device="cuda", compute_type="float16")

    def unload(self) -> None:
        if self._model is None:
            return
        del self._model
        self._model = None
        import gc
        import torch
        gc.collect()
        torch.cuda.empty_cache()

    def transcribe(
        self,
        wav_path: str,
        progress_cb: ProgressCB | None = None,
        language: str | None = None,
    ) -> list[Segment]:
        if self._model is None:
            raise RuntimeError("Whisper not loaded; call load() first")

        # beam_size=5 for accuracy; vad_filter for long-form; word_timestamps
        # on so the UI can show them; no conditioning on prev text (avoids the
        # classic repetition loop, acceptable tradeoff per plan).
        raw_segs, info = self._model.transcribe(
            wav_path,
            language=language,
            word_timestamps=True,
            vad_filter=True,
            beam_size=5,
            condition_on_previous_text=False,
        )
        self.detected_language = getattr(info, "language", None)

        total = max(getattr(info, "duration", 0.0) or 0.0, 1.0)
        segments: list[Segment] = []
        last_reported = 0.0
        for s in raw_segs:
            words = []
            if s.words:
                words = [
                    Word(text=w.word.strip(), start=w.start, end=w.end) for w in s.words
                ]
            segments.append(
                Segment(
                    start=s.start,
                    end=s.end,
                    text=s.text.strip(),
                    words=words,
                )
            )
            if progress_cb and (s.end - last_reported) > 5.0:
                progress_cb(min(1.0, s.end / total), f"whisper {s.end/1:.0f}s")
                last_reported = s.end
        if progress_cb:
            progress_cb(1.0, "whisper done")
        return [s for s in segments if s.text]

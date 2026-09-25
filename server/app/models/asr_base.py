"""Common ASR interface.

A Transcriber is loaded on demand into the single ASR slot (see manager.py),
transcribes the canonical 16 kHz mono WAV, and is unloaded before any other
heavy model (Ollama) is used. The concrete backends (Canary, Whisper) hide
their word-timestamp strategy behind `transcribe()`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Segment:
    """One ASR text chunk with a time span. `speaker` is filled later by
    alignment; `words` may be empty when the backend can't word-timestamp."""

    start: float
    end: float
    text: str
    speaker: str | None = None
    words: list[Word] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "text": self.text,
            "speaker": self.speaker,
            "words": [
                {"text": w.text, "start": round(w.start, 3), "end": round(w.end, 3)}
                for w in self.words
            ],
        }


# progress callback signature: (fraction_done: float, message: str) -> None
ProgressCB = Callable[[float, str], None]


@runtime_checkable
class Transcriber(Protocol):
    name: str

    def load(self) -> None:
        """Load the model onto CUDA. Idempotent if already loaded."""

    def unload(self) -> None:
        """Free the model (del + gc + torch.cuda.empty_cache)."""

    def transcribe(self, wav_path: str, progress_cb: ProgressCB | None = None) -> list[Segment]:
        """Transcribe the 16 kHz mono wav. Must be called after load()."""

    def is_loaded(self) -> bool:
        ...

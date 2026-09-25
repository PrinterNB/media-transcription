"""pyannote speaker diarization wrapper.

Runs on the same 16 kHz mono WAV regardless of which ASR was chosen (the plan
requires speaker separation to happen before naming and be ASR-independent).
Lives in its own resident slot in the manager — it's ~1 GB and we keep it warm
across jobs.

Gated model: needs HF_TOKEN. A missing token or a 403 raises a friendly
DiarizationError naming the exact HF pages + where the token goes.
"""
from __future__ import annotations

from dataclasses import dataclass


class DiarizationError(Exception):
    pass


@dataclass
class DiarizationTrack:
    """One contiguous same-speaker span (pyannote `itertracks` output)."""

    start: float
    end: float
    speaker: str


class Diarizer:
    def __init__(self, model_id: str, hf_token: str) -> None:
        self.model_id = model_id
        self.hf_token = hf_token
        self._pipe = None

    def is_loaded(self) -> bool:
        return self._pipe is not None

    def load(self) -> None:
        if self._pipe is not None:
            return
        if not self.hf_token:
            raise DiarizationError(
                "Speaker diarization needs a Hugging Face token (the pyannote model "
                "is gated). Get one at https://huggingface.co/settings/tokens and set "
                "HF_TOKEN in .env. You must also accept the model terms at "
                "https://huggingface.co/pyannote/speaker-diarization-3.1 — then "
                "diarization will work."
            )
        import torch
        from pyannote.audio import Pipeline

        try:
            self._pipe = Pipeline.from_pretrained(
                self.model_id, use_auth_token=self.hf_token
            )
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "403" in msg or "gated" in msg.lower() or "force" in msg.lower():
                raise DiarizationError(
                    "Could not download the gated pyannote model (403). Confirm your "
                    "HF_TOKEN has read access and you've accepted the model terms at "
                    "https://huggingface.co/pyannote/speaker-diarization-3.1, and that "
                    f"HF_TOKEN is set. Details: {msg}"
                ) from e
            raise
        self._pipe.to(torch.device("cuda")).eval()
        try:
            self._pipe = self._pipe.instantiate({"use_speaker_verification": True})
        except Exception:  # noqa: BLE001
            # use_speaker_verification needs extra weights; not fatal.
            pass

    def unload(self) -> None:
        if self._pipe is not None:
            del self._pipe
            self._pipe = None
            import gc
            import torch
            gc.collect()
            torch.cuda.empty_cache()

    def diarize(self, wav_path: str) -> list[DiarizationTrack]:
        if self._pipe is None:
            self.load()
        res = self._pipe({"waveform": wav_path, "sample_rate": 16000})
        tracks: list[DiarizationTrack] = []
        for turn, _, speaker in res.itertracks(yield_label=True):
            tracks.append(DiarizationTrack(start=turn.start, end=turn.end, speaker=speaker))
        return tracks

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

from ..config import local_model_dir


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
        # Manual install (README, option B): the gated repo's files under
        # models/pyannote-speaker-diarization-3.1/ — no HF token needed.
        local = local_model_dir("pyannote-speaker-diarization-3.1")
        if local is None and not self.hf_token:
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
            if local is not None:
                # Pipeline.from_pretrained takes the config file (or a hub id),
                # not a directory — point it at the folder's config.yaml.
                config_yml = local / "config.yaml"
                if not config_yml.is_file():
                    raise DiarizationError(
                        f"Manual pyannote install is incomplete: {config_yml} is "
                        "missing. Put the whole gated repo (config.yaml, handler.py) "
                        "in that folder — see the README (option B)."
                    )
                self._pipe = Pipeline.from_pretrained(str(config_yml))
            else:
                self._pipe = Pipeline.from_pretrained(
                    self.model_id, use_auth_token=self.hf_token
                )
        except DiarizationError:
            raise
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

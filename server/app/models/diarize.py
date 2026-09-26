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
        # Manual install (README, option B): the pipeline config under
        # models/pyannote-speaker-diarization-3.1/. NOTE the underlying
        # segmentation model is still downloaded from the hub and is gated
        # too, so a token is still required (see gated_hint below).
        local = local_model_dir("pyannote-speaker-diarization-3.1")
        if local is None and not self.hf_token:
            raise DiarizationError(
                "Speaker diarization needs a Hugging Face token (the pyannote "
                "models are gated). Get one at https://huggingface.co/settings/"
                "tokens and set HF_TOKEN in .env. You must also accept the "
                "model terms at BOTH https://huggingface.co/pyannote/"
                "speaker-diarization-3.1 AND https://huggingface.co/pyannote/"
                "segmentation-3.0 — then diarization will work."
            )
        import torch
        from pyannote.audio import Pipeline

        # The diarization pipeline downloads TWO gated repos: its own
        # speaker-diarization-3.1 AND the segmentation-3.0 model named in its
        # config. A 403 on either one must name both pages below.
        gated_hint = (
            "Could not download the gated pyannote diarization models. With "
            "your logged-in Hugging Face account, accept the terms for BOTH "
            "repos —\n"
            "  1. https://huggingface.co/pyannote/speaker-diarization-3.1\n"
            "  2. https://huggingface.co/pyannote/segmentation-3.0\n"
            "— then make sure a valid HF_TOKEN is set in .env (create one at "
            "https://huggingface.co/settings/tokens)."
        )

        # The pyannote checkpoints in this venv predate PyTorch 2.6's
        # weights_only=True torch.load default; pl_load raises
        # UnpicklingError without the override. (We trust HF-hub sources.)
        orig_torch_load = torch.load

        def _lenient_torch_load(*args, **kwargs):
            # lightning passes weights_only=None, which torch 2.6+ reads as True
            if kwargs.get("weights_only") is None:
                kwargs["weights_only"] = False
            return orig_torch_load(*args, **kwargs)

        torch.load = _lenient_torch_load
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
            # pyannote swallows a gated-repo download failure: Model.from_
            # pretrained prints "Could not download ..." and returns None,
            # which then surfaces as "'NoneType' object has no attribute
            # 'eval'". Map that onto the same friendly error.
            msg = str(e)
            if (
                "403" in msg
                or "gated" in msg.lower()
                or "force" in msg.lower()
                or (type(e).__name__ == "AttributeError" and "NoneType" in msg)
            ):
                raise DiarizationError(gated_hint + f"\nDetails: {msg}") from e
            raise
        finally:
            torch.load = orig_torch_load
        if self._pipe is None:  # from_pretrained gives up and returns None
            raise DiarizationError(gated_hint)
        # NB: no .eval() here — pyannote's Pipeline is not an nn.Module.
        self._pipe.to(torch.device("cuda"))
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
        # Pass the path itself: the pipeline's Audio loader loads, resamples
        # (16 kHz) and downmixes. (The old {"waveform": <path>} dict form is
        # wrong for pyannote.audio 3.x — "waveform" must be a (ch, time)
        # tensor, and a path there crashes validate_file.)
        res = self._pipe(wav_path)
        tracks: list[DiarizationTrack] = []
        for turn, _, speaker in res.itertracks(yield_label=True):
            tracks.append(DiarizationTrack(start=turn.start, end=turn.end, speaker=speaker))
        return tracks

"""Model backends: ASR (Canary/Whisper), diarization (pyannote), manager.

Device policy for the whole package lives HERE, in one place, so no backend
module hardcodes a device (macOS-only branch; the NVIDIA-GPU path that
needed Windows was deleted entirely):

  * torch backends (Canary, pyannote): torch_device() -> "mps" when the
    MPS backend is feature-detected available, else "cpu".
  * faster-whisper: ctranslate_device() -> "cpu", always. The ctranslate2
    runtime behind faster-whisper ships only its cpu and NVIDIA-GPU device
    implementations; MPS was never offered there, and the GPU one is gone
    — so the M1 GPU helps the torch models, not Whisper.

dtype is per backend and lives next to each load() call (it depends on what
that backend's weights are reliable in on the MPS/CPU backends).

The never-concurrent memory rule — Ollama naming never runs while ASR or
diarization is resident — is documented and enforced in manager.py; this
file only decides *where* a resident model sits, never *what else* is
resident alongside it.
"""
from __future__ import annotations


def torch_device() -> str:
    """Resolve the torch device once: "mps" if MPS works, else "cpu".

    Feature-detected via torch.backends.mps.is_available() — we never
    `import torch.mps` (that submodule explodes on torch wheels built
    without MPS) and we keep no NVIDIA-GPU fallback branch: deleted with
    Windows support. torch is imported inside the function so the app can
    still boot in a venv without it (same lazy-import rule as every heavy
    dep).
    """
    try:
        import torch

        if torch.backends.mps.is_available():
            return "mps"
    except Exception:  # noqa: BLE001 — torch absent / MPS-less wheel: honest CPU
        pass
    return "cpu"


def ctranslate_device() -> str:
    """faster-whisper's device. ctranslate2 (the C++ engine WhisperModel wraps)
    implements only its cpu and NVIDIA-GPU devices — MPS is not a device it
    accepts — and the GPU one was deleted, so Whisper is unconditionally
    "cpu" on this branch (see asr_whisper.load for the matching compute_type).
    """
    return "cpu"


def free_torch_cache() -> None:
    """Return freed tensors to the right allocator, device-aware.

    MPS keeps a caching allocator of its own: free it with
    torch.mps.empty_cache(), reached as an attribute under the
    is_available() guard (a bare `import torch.mps` breaks MPS-less torch
    wheels). CPU has nothing left once gc drops the tensors, so this is a
    no-op there. Best-effort and never raises: whisper's ctranslate2 stack
    works without torch importable at all.
    """
    try:
        import torch

        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:  # noqa: BLE001 — nothing we can free: no torch, no MPS
        pass

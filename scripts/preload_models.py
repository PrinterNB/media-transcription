"""One-off model preload: warm every model cache with a real (download-only)
load, so the first production job doesn't wait on ~9 GB of downloads.

Run with the venv Python (NOT `python` from PATH):

    .venv\\Scripts\\python scripts\\preload_models.py

Each step is independent — a failure in one prints and the rest still run.
Heavy imports happen inside each step on purpose, so the script works even
when one of the deps is missing/broken. Models are loaded on CPU where the
app would use CUDA (this pass is about filling the HF cache, not measuring
speed) and discarded afterwards.
"""
from __future__ import annotations

import os
import sys
import time

CANARY_MODEL = os.environ.get("CANARY_MODEL", "nvidia/canary-qwen-2.5b")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "large-v3")
DIARIZATION_MODEL = os.environ.get(
    "DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1"
)


def hf_cache_dir() -> str:
    """Where Hugging Face caches land (same constant the libs use)."""
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
        return HF_HUB_CACHE
    except Exception:  # noqa: BLE001 — huggingface_hub not importable
        return os.path.join(
            os.path.expanduser("~"), ".cache", "huggingface", "hub"
        )


def _discard(obj) -> None:
    del obj
    import gc
    gc.collect()


def step_canary() -> None:
    print(f"  importing nemo (first import is slow, ~30 s)...", flush=True)
    # Canary is a NeMo speech-LM (SALM) — transformers-direct is broken on it
    # (DiaConfig), see docs/spike-notes.md.
    from nemo.collections.speechlm2.models import SALM

    print(f"  loading {CANARY_MODEL} (~5.5 GB, downloads on first run)...", flush=True)
    model = SALM.from_pretrained(CANARY_MODEL)
    _discard(model)
    print("  canary: cached and discarded.", flush=True)


def step_whisper() -> None:
    print(f"  importing faster_whisper...", flush=True)
    from faster_whisper import WhisperModel

    print(f"  loading {WHISPER_MODEL} (~3.1 GB, downloads on first run)...", flush=True)
    # cpu + default compute is fine for a download-only pass; much cheaper
    # than spinning up the CUDA context just to touch the weights.
    model = WhisperModel(WHISPER_MODEL, device="cpu")
    _discard(model)
    print("  whisper: cached and discarded.", flush=True)


def step_pyannote() -> None:
    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        print(
            "  HF_TOKEN is not set — skipping (the pyannote model is gated).\n"
            "  Same error the app would give you:\n"
            "    Speaker diarization needs a Hugging Face token (the pyannote\n"
            "    model is gated). Get one at https://huggingface.co/settings/tokens\n"
            "    and set HF_TOKEN in .env. You must also accept the model terms\n"
            "    at https://huggingface.co/pyannote/speaker-diarization-3.1 —\n"
            "    then diarization will work."
        )
        return
    print("  importing pyannote.audio...", flush=True)
    from pyannote.audio import Pipeline

    print(f"  loading {DIARIZATION_MODEL} (downloads on first run)...", flush=True)
    pipe = Pipeline.from_pretrained(DIARIZATION_MODEL, use_auth_token=token)
    try:
        # Same as the app's Diarizer.load(); not fatal if the extra
        # speaker-verification weights are unavailable.
        pipe.instantiate({"use_speaker_verification": True})
    except Exception:  # noqa: BLE001
        pass
    _discard(pipe)
    print("  pyannote: cached and discarded.", flush=True)


STEPS = [
    ("canary (ASR, English)", step_canary),
    ("whisper (ASR, multilingual)", step_whisper),
    ("pyannote (diarization)", step_pyannote),
]


def main() -> int:
    print("=" * 62)
    print("Preloading model caches")
    print(f"  HF cache dir: {hf_cache_dir()}")
    print("=" * 62)

    ok: list[bool] = []
    for name, step in STEPS:
        print(f"[{name}]")
        t0 = time.time()
        try:
            step()
            ok.append(True)
            print(f"  -> OK in {time.time() - t0:.0f}s", flush=True)
        except Exception as e:  # noqa: BLE001 — report and keep going
            ok.append(False)
            print(
                f"  -> FAILED after {time.time() - t0:.0f}s: "
                f"{type(e).__name__}: {e}",
                flush=True,
            )

    print("=" * 62)
    failed = len(STEPS) - sum(ok)
    if failed:
        print(f"{failed}/{len(STEPS)} step(s) failed — see above. Re-run this script "
              "after fixing the cause.")
        return 1
    print("All model caches are warm. The first real job will load fast.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""One-off model preload: warm every model cache with a real (download-only)
load, so the first production job doesn't wait on ~9 GB of downloads.

Run with the venv Python (NOT `python` from PATH):

    .venv\\Scripts\\python scripts\\preload_models.py
    .venv\\Scripts\\python scripts\\preload_models.py --local-only

--local-only: only use models that are already here (Hugging Face cache OR a
manual install under MODELS_DIR, default ./models) — never touches the
network. For air-gapped verification.

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
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]

CANARY_MODEL = os.environ.get("CANARY_MODEL", "nvidia/canary-qwen-2.5b")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "large-v3")
DIARIZATION_MODEL = os.environ.get(
    "DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1"
)

# Where this script looks for the README "option B" manual installs
# (same resolution rule as server/app/config.py — the script deliberately
# does not import the app package).
LOCAL_MODELS_DIR = Path(os.environ.get("MODELS_DIR", "models"))
if not LOCAL_MODELS_DIR.is_absolute():
    LOCAL_MODELS_DIR = _PROJECT_ROOT / LOCAL_MODELS_DIR

LOCAL_WHISPER_DIR = LOCAL_MODELS_DIR / "faster-whisper-large-v3"
LOCAL_CANARY_DIR = LOCAL_MODELS_DIR / "canary-qwen-2.5b"

# True under --local-only (set by main()) — cached/manual models only.
LOCAL_ONLY = False

# The files each hub snapshot must hold before we treat its cache as complete
# (and thus safe to skip). If any are missing — e.g. after a WinError 1314
# dropped a file out of the snapshot dir — we clean and re-run the load.
CANARY_FILES = ("config.json", "model.safetensors")
WHISPER_FILES = (
    "model.bin",
    "config.json",
    "tokenizer.json",
    "preprocessor_config.json",
    "vocabulary.json",
)


def local_present(name: str) -> Path | None:
    """Return <MODELS_DIR>/<name> if a manual install exists there, else None."""
    p = LOCAL_MODELS_DIR / name
    return p if p.is_dir() else None


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


def _repo_dir(repo_id: str) -> Path:
    """Cache folder for a hub id: <hf_cache>/models--<ns>--<name>."""
    parts = repo_id.split("/")
    ns, name = (parts[0], "/".join(parts[1:])) if len(parts) > 1 else ("", repo_id)
    return Path(hf_cache_dir()) / f"models--{ns}--{name}"


def _cleanup_repo(repo_id: str, keep_blobs: bool = True) -> None:
    """Drop a partially-downloaded cache repo (or just its snapshots/).

    Windows quirk ([WinError 1314], a required privilege is not held by the
    client): huggingface_hub fails to move a freshly downloaded blob into the
    snapshot dir. Removing the snapshot dir lets the retry re-link the blobs
    that survived (content-addressed, they stay put in blobs/); with
    keep_blobs=False the whole repo folder is dropped for a clean re-download.
    """
    d = _repo_dir(repo_id)
    if not d.is_dir():
        return
    target = d if not keep_blobs else (d / "snapshots")
    if not target.is_dir():
        return
    print(f"  (cleaning partial cache: {target})", flush=True)
    import shutil
    # ignore_errors: a still-locked file (the very WinError 1314 we're
    # retrying around) shouldn't abort the cleanup — we re-raise the original
    # load error afterwards, not a cleanup hiccup.
    shutil.rmtree(target, ignore_errors=True)


def _final_hint(repo_id: str) -> str:
    return (
        f"If this keeps failing: delete {_repo_dir(repo_id)} and re-run, or use "
        "the manual download option (README → Option B)."
    )


def _with_hub_retry(repo_id: str, attempts: int = 3):
    """Wrap `fn()` to retry half-finished HF downloads.

    Usage: `_with_hub_retry(repo_id)(fn)`. huggingface_hub downloads each
    file into a content-addressed blob and moves it into the snapshot dir at
    the end; if that move fails (Windows [WinError 1314], "a required
    privilege is not held by the client" — a file-lock/privilege glitch) a
    partial snapshot is left behind. Drop the snapshot dir and retry; after
    the last attempt drop the whole cache repo so the next manual run starts
    clean.
    """
    import huggingface_hub

    def wrapped(fn):
        last_exc: Exception | None = None
        for i in range(attempts):
            try:
                return fn()
            except huggingface_hub.errors.OfflineModeIsEnabled:
                # Deliberately offline (HF_HUB_OFFLINE) — retrying won't help;
                # must precede the OSError branch (it's a ConnectionError).
                raise
            except OSError as e:  # [WinError 1314] and other move/download errors
                last_exc = e
                msg = f"{type(e).__name__}: {e}"
            except Exception as e:  # noqa: BLE001 — hub/network errors
                last_exc = e
                msg = f"{type(e).__name__}: {e}"
                if not any(
                    s in msg.lower()
                    for s in ("1314", "connection", "timeout", "temporarily")
                ):
                    raise
            print(f"  download hiccup ({msg[:160]}) — attempt {i + 1}/{attempts}",
                  flush=True)
            if i + 1 < attempts:
                _cleanup_repo(repo_id)
        _cleanup_repo(repo_id, keep_blobs=False)
        raise RuntimeError(  # noqa: BLE001 — reported by main(), with hint
            f"{type(last_exc).__name__}: {last_exc} — {_final_hint(repo_id)}"
        ) from last_exc

    return wrapped


def _snapshot_ok(repo_id: str, needed: tuple[str, ...]) -> bool:
    """True if a cache snapshot of `repo_id` holds every file in `needed`."""
    d = _repo_dir(repo_id)
    snaps = sorted((d / "snapshots").iterdir(), reverse=True) if d.is_dir() else []
    for snap in snaps:
        if all((snap / f).is_file() for f in needed):
            return True
    return False


def step_canary() -> None:
    if local_present("canary-qwen-2.5b"):
        # Manual install (README option B) — load the real thing, offline.
        # (Works with or without --local-only; a local folder is local.)
        print(
            f"  loading {LOCAL_CANARY_DIR} (manual install, no network)...",
            flush=True,
        )
        from nemo.collections.speechlm2.models import SALM
        model = SALM.from_pretrained(str(LOCAL_CANARY_DIR), local_files_only=True)
        _discard(model)
        print("  canary: loaded from manual install.", flush=True)
        return
    if LOCAL_ONLY:
        if _snapshot_ok(CANARY_MODEL, CANARY_FILES):
            print("  canary: found in HF cache — skipping (local-only).")
            return
        raise RuntimeError(
            f"not available offline: {CANARY_MODEL} is not in the HF cache "
            f"and {LOCAL_CANARY_DIR} does not exist (option B)."
        )
    print("  importing nemo (first import is slow, ~30 s)...", flush=True)
    # Canary is a NeMo speech-LM (SALM) — transformers-direct is broken on it
    # (DiaConfig), see docs/spike-notes.md.
    from nemo.collections.speechlm2.models import SALM

    print(f"  loading {CANARY_MODEL} (~5.5 GB, downloads on first run)...", flush=True)
    model = _with_hub_retry(CANARY_MODEL, 2)(lambda: SALM.from_pretrained(CANARY_MODEL))
    _discard(model)
    print("  canary: cached and discarded.", flush=True)


def step_whisper() -> None:
    if local_present("faster-whisper-large-v3"):
        # Manual install (README option B) — load the real thing, offline.
        # (Works with or without --local-only; a local folder is local.)
        print(
            f"  loading {LOCAL_WHISPER_DIR} (manual install, no network)...",
            flush=True,
        )
        from faster_whisper import WhisperModel
        model = WhisperModel(str(LOCAL_WHISPER_DIR), device="cpu", local_files_only=True)
        _discard(model)
        print("  whisper: loaded from manual install.", flush=True)
        return
    if LOCAL_ONLY:
        if _snapshot_ok(WHISPER_MODEL, WHISPER_FILES):
            print("  whisper: found in HF cache — skipping (local-only).")
            return
        raise RuntimeError(
            f"not available offline: {WHISPER_MODEL} is not in the HF cache "
            f"and {LOCAL_WHISPER_DIR} does not exist (option B)."
        )
    print("  importing faster_whisper...", flush=True)
    from faster_whisper import WhisperModel

    print(f"  loading {WHISPER_MODEL} (~3.1 GB, downloads on first run)...", flush=True)
    # cpu + default compute is fine for a download-only pass; much cheaper
    # than spinning up the CUDA context just to touch the weights.
    model = _with_hub_retry(WHISPER_MODEL)(
        lambda: WhisperModel(WHISPER_MODEL, device="cpu")
    )
    _discard(model)
    print("  whisper: cached and discarded.", flush=True)


def step_pyannote() -> None:
    token = os.environ.get("HF_TOKEN", "").strip()
    if LOCAL_ONLY:
        if local_present("pyannote-speaker-diarization-3.1"):
            print("  pyannote: manual install found — skipping network check.")
            return
        if token:
            print("  pyannote: HF_TOKEN set, but not checked (local-only).")
        else:
            print("  pyannote: no HF_TOKEN and no manual install — skipped (local-only).")
        return
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
    pipe = _with_hub_retry(DIARIZATION_MODEL)(
        lambda: Pipeline.from_pretrained(DIARIZATION_MODEL, use_auth_token=token)
    )
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
    global LOCAL_ONLY
    LOCAL_ONLY = "--local-only" in sys.argv

    print("=" * 62)
    print("Preloading model caches")
    print(f"  HF cache dir: {hf_cache_dir()}")
    print(f"  manual-install dir: {LOCAL_MODELS_DIR} "
          f"({'present' if LOCAL_MODELS_DIR.is_dir() else 'absent'})")
    if LOCAL_ONLY:
        print("  --local-only: using cached/manual models only, no network.")
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

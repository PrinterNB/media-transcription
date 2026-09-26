"""App configuration: env + .env -> frozen dataclass.

No pydantic-settings — keeps the dependency surface small. Reads .env from
the project root (cwd) then the process environment; later values win.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _load_dotenv(root: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines, # comments, no interpolation)."""
    env_file = root / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def settings() -> "Settings":
    _load_dotenv(_PROJECT_ROOT)

    data_dir = Path(os.environ.get("DATA_DIR", "data"))
    if not data_dir.is_absolute():
        data_dir = _PROJECT_ROOT / data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "uploads").mkdir(exist_ok=True)
    (data_dir / "outputs").mkdir(exist_ok=True)

    # Manually-downloaded models (README, option B). Not created here — a
    # missing folder just means "load everything from the Hugging Face hub".
    models_dir = Path(os.environ.get("MODELS_DIR", "models"))
    if not models_dir.is_absolute():
        models_dir = _PROJECT_ROOT / models_dir

    return Settings(
        data_dir=data_dir,
        uploads_dir=data_dir / "uploads",
        outputs_dir=data_dir / "outputs",
        db_path=data_dir / "transcription.db",
        models_dir=models_dir,
        hf_token=os.environ.get("HF_TOKEN", ""),
        ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        ollama_model=os.environ.get("OLLAMA_MODEL", "qwen-fast"),
        canary_model=os.environ.get("CANARY_MODEL", "nvidia/canary-qwen-2.5b"),
        whisper_model=os.environ.get("WHISPER_MODEL", "large-v3"),
        diarization_model=os.environ.get(
            "DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1"
        ),
        asr_default=os.environ.get("ASR_DEFAULT", "canary"),
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
    )


def local_model_dir(name: str) -> Path | None:
    """Return ``<MODELS_DIR>/<name>`` if that folder exists, else ``None``.

    A populated folder (manual download, README option B) is loaded in
    preference to the Hugging Face hub id; when it is absent the loaders fall
    back to the hub exactly as before.
    """
    p = settings().models_dir / name
    return p if p.is_dir() else None


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    uploads_dir: Path
    outputs_dir: Path
    db_path: Path
    models_dir: Path
    hf_token: str
    ollama_url: str
    ollama_model: str
    canary_model: str
    whisper_model: str
    diarization_model: str
    asr_default: str
    host: str
    port: int

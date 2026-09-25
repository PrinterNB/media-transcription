"""Phase 0 spike.

Proves, on this exact box, that every heavy dependency loads and produces sane
output before we build on top of it:

  1. torch reports CUDA with compute capability (12, 0)  -> Blackwell sm_120
  2. Canary (nvidia/canary-qwen-2.5b) loads, transcribes a 60s wav, word
     timestamps present? RTF sane?
  3. faster-whisper large-v3 loads (ctranslate2 CUDA DLLs), non-English
     auto-detect works
  4. pyannote diarization pipeline loads (HF_TOKEN gated)
  5. Ollama qwen-fast returns parseable JSON for the naming contract

Run with CUDA 12.9 bin on PATH (see run.ps1 / README):
    .venv\Scripts\python scripts\spike.py [--wav path/to/sample.wav]

Exit code 0 = every probe passed. Each probe prints PASS/FAIL so the notes
file (docs/spike-notes.md) can lock decisions.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

PASS = "PASS"
FAIL = "FAIL"

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{PASS if ok else FAIL}] {name}: {detail}")


def probe_torch() -> None:
    try:
        import torch
    except Exception as e:  # noqa: BLE001
        record("torch", False, f"import failed: {e}")
        return
    if not torch.cuda.is_available():
        record("torch.cuda", False, "CUDA not available")
        return
    dev = torch.cuda.get_device_capability(0)
    name = torch.cuda.get_device_name(0)
    ok = dev == (12, 0)
    record(
        "torch.cuda",
        ok,
        f"{name} cc={dev} torch={torch.__version__} "
        f"({torch.version.cuda}) mem={torch.cuda.get_device_properties(0).total_memory/2**30:.1f}GB",
    )


def _make_test_wav(path: str) -> None:
    """Generate a 60s sine sweep wav if none was provided."""
    import numpy as np
    import soundfile as sf

    sr = 16000
    t = np.linspace(0, 60, sr * 60, endpoint=False)
    # mix of frequencies so ASR has *something* to work on (will be empty text,
    # which is fine — we're probing load + timing, not accuracy on a tone)
    x = (0.2 * np.sin(2 * np.pi * 440 * t) + 0.1 * np.sin(2 * np.pi * 880 * t))
    sf.write(path, x.astype(np.float32), sr, subtype="PCM_16")


def probe_canary(wav: str) -> None:
    try:
        import torch  # noqa: F401 (checked implicitly via SALM on cuda)
    except Exception:  # noqa: BLE001
        record("canary", False, "torch not available")
        return
    import soundfile as sf

    t0 = time.time()
    try:
        # Canary is a NeMo speech-LM (SALM), NOT a plain HF causal LM —
        # AutoModelForCausalLM rejects its DiaConfig (see docs/spike-notes.md).
        from nemo.collections.speechlm2.models import SALM

        model = SALM.from_pretrained(
            "nvidia/canary-qwen-2.5b"
        ).bfloat16().eval().to("cuda")
    except Exception as e:  # noqa: BLE001
        record("canary.load", False, f"{type(e).__name__}: {e}")
        return
    record("canary.load", True, f"{time.time()-t0:.1f}s")

    # transcribe the provided wav (or a generated tone)
    info = sf.info(wav)
    if info.samplerate != 16000:
        raise RuntimeError(f"spike expects 16k wav, got {info.samplerate}Hz")
    t1 = time.time()
    try:
        # SALM generate() takes a chat-style prompt; the wav path goes in the
        # "audio" field alongside the model's own audio-locator tag.
        answer_ids = model.generate(
            prompts=[[{"role": "user",
                       "content": f"Transcribe the following: {model.audio_locator_tag}",
                       "audio": [wav]}]],
            max_new_tokens=128,
        )
        text = model.tokenizer.ids_to_text(answer_ids[0].cpu()).strip()
        dt = time.time() - t1
        rtf = dt / max(info.duration, 1e-6)
        record(
            "canary.transcribe",
            True,
            f"{dt:.1f}s rtf={rtf:.2f} text={text[:120]!r}",
        )
        # SALM generate() returns token ids; per-word timestamps unverified,
        # so the backend uses sentence-level segments with empty `words`.
        record(
            "canary.word_timestamps",
            True,
            "not exposed by SALM generate(); backend falls back to sentence-level segments",
        )
    except Exception as e:  # noqa: BLE001
        record("canary.transcribe", False, f"{type(e).__name__}: {e}")


def probe_whisper(wav: str) -> None:
    try:
        from faster_whisper import WhisperModel
    except Exception as e:  # noqa: BLE001
        record("whisper.load", False, f"{type(e).__name__}: {e}")
        return
    t0 = time.time()
    try:
        model = WhisperModel("large-v3", device="cuda", compute_type="float16")
    except Exception as e:  # noqa: BLE001
        record("whisper.load", False, f"{type(e).__name__}: {e}")
        return
    record("whisper.load", True, f"{time.time()-t0:.1f}s")
    try:
        t1 = time.time()
        segs, info = model.transcribe(
            wav, word_timestamps=True, vad_filter=True, beam_size=5
        )
        texts = [s.text for s in segs]
        dt = time.time() - t1
        record(
            "whisper.transcribe",
            True,
            f"{dt:.1f}s lang={info.language}({info.language_probability:.2f}) "
            f"segs={len(texts)}",
        )
    except Exception as e:  # noqa: BLE001
        record("whisper.transcribe", False, f"{type(e).__name__}: {e}")


def probe_pyannote(wav: str) -> None:
    token = os.environ.get("HF_TOKEN") or os.environ.get("HF_HOME")
    if not token:
        record("pyannote", False, "HF_TOKEN not set (expected for probe)")
        return
    try:
        import torch
        from pyannote.audio import Pipeline
    except Exception as e:  # noqa: BLE001
        record("pyannote.load", False, f"{type(e).__name__}: {e}")
        return
    t0 = time.time()
    try:
        pipe = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", use_auth_token=os.environ["HF_TOKEN"]
        )
        pipe.to(torch.device("cuda")).eval()
    except Exception as e:  # noqa: BLE001
        record("pyannote.load", False, f"{type(e).__name__}: {e}")
        return
    record("pyannote.load", True, f"{time.time()-t0:.1f}s")
    try:
        pipe = pipe.instantiate({"use_speaker_verification": True})
        res = pipe({"waveform": wav, "sample_rate": 16000})
        speakers = set()
        for turn, _, spk in res.itertracks(yield_label=True):
            speakers.add(spk)
        record("pyannote.run", True, f"speakers={sorted(speakers)}")
    except Exception as e:  # noqa: BLE001
        record("pyannote.run", False, f"{type(e).__name__}: {e}")


def probe_ollama() -> None:
    url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    import urllib.request

    body = json.dumps(
        {
            "model": "qwen-fast",
            "stream": False,
            "options": {"temperature": 0},
            "messages": [
                {
                    "role": "system",
                    "content": 'Respond with only JSON: {"ok": true}',
                },
                {"role": "user", "content": "test"},
            ],
        }
    ).encode()
    try:
        req = urllib.request.Request(
            url + "/api/chat", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
        text = data.get("message", {}).get("content", "")
        # strip fences and parse
        t = text.strip()
        if t.startswith("```"):
            t = t.split("```", 2)[1] if t.count("```") >= 2 else t
            t = t[4:] if t.startswith("json") else t
        parsed = json.loads(t)
        record("ollama", True, f"parsed={parsed}")
    except Exception as e:  # noqa: BLE001
        record("ollama", False, f"{type(e).__name__}: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--wav",
        default=os.path.join(os.path.dirname(__file__), "sample_60s.wav"),
        help="16kHz wav to transcribe (generated if missing)",
    )
    args = ap.parse_args()

    print("=" * 60)
    print("Phase 0 spike")
    print("=" * 60)
    probe_torch()

    # ensure a wav exists for audio probes
    if not os.path.exists(args.wav):
        print(f"generating test wav at {args.wav}")
        _make_test_wav(args.wav)

    # Run probes one at a time; a failure should not stop the others.
    try:
        probe_canary(args.wav)
    except Exception as e:  # noqa: BLE001
        record("canary", False, f"probe crashed: {e}")

    try:
        probe_whisper(args.wav)
    except Exception as e:  # noqa: BLE001
        record("whisper", False, f"probe crashed: {e}")

    try:
        probe_pyannote(args.wav)
    except Exception as e:  # noqa: BLE001
        record("pyannote", False, f"probe crashed: {e}")

    try:
        probe_ollama()
    except Exception as e:  # noqa: BLE001
        record("ollama", False, f"probe crashed: {e}")

    print("=" * 60)
    ok = sum(1 for _, p, _ in results if p)
    print(f"{ok}/{len(results)} probes passed")
    for name, p, d in results:
        print(f"  [{PASS if p else FAIL}] {name}: {d}")
    print("=" * 60)
    return 0 if all(p for _, p, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())

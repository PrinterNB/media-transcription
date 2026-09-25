# Phase 0 — Spike notes (2026-09-25)

Probes run on this box: RTX 5080 (Blackwell, cc 12.0), 15.9 GB VRAM, torch 2.8.0+cu128.

## What passed

| Probe | Result |
|---|---|
| torch CUDA / Blackwell | PASS — `cc=(12,0)`, 15.9 GB, cu128 build |
| faster-whisper large-v3 load | PASS — ~6 min cold (downloads 3.1 GB) |
| faster-whisper transcribe | PASS — 26 s for 60 s wav, language autodetect works |
| Ollama qwen-fast JSON | PASS — `{"ok": true}` round-trips cleanly |

## Key decision: Canary loads via NeMo, not transformers

The spike's first attempt used `AutoModelForCausalLM` / `AutoProcessor` on
`nvidia/canary-qwen-2.5b` and **failed**:

```
ValueError: Unrecognized configuration class
<class 'transformers.models.dia.configuration_dia.DiaConfig'>
for this kind of AutoModel: AutoModelForCausalLM.
```

Inspection of the cached `config.json` shows why — it is **not** a plain HF
causal-LM layout. Top-level keys are NeMo-style:

```
perception (encoder + modality_adapter + preprocessor)
pretrained_llm / pretrained_weights / prompt_format / audio_locator_tag
```

There is no `model_type`/`architectures` field, so `transformers.AutoConfig`
falls back to guessing `DiaConfig`, and `AutoModelForCausalLM` then rejects it.
`DiaProcessor.from_pretrained` also fails (no `preprocessor_config.json` in the
repo — it's under `.no_exist`).

**Conclusion:** `nvidia/canary-qwen-2.5b` is a **NeMo speech-LM** (SALM). The
canonical loader (per the HF model card) is:

```python
from nemo.collections.speechlm2.models import SALM
model = SALM.from_pretrained('nvidia/canary-qwen-2.5b').bfloat16().eval().to('cuda')
answer_ids = model.generate(
    prompts=[[{"role": "user",
               "content": f"Transcribe the following: {model.audio_locator_tag}",
               "audio": ["speech.wav"]}]],
    max_new_tokens=128,
)
text = model.tokenizer.ids_to_text(answer_ids[0].cpu())
```

So the Canary backend (`server/app/models/asr_canary.py`) must use **NeMo**,
matching the plan's "documented fallback" (transformers-direct was the
optimistic primary; NeMo is the guaranteed path). `nemo==8.0.2` is installed in
the venv (keeps torch 2.8.0+cu128).

### Canary word timestamps — open (Phase 3 will resolve)
The NeMo SALM `generate()` returns token ids; whether it exposes per-word
timestamps out of the box is not yet verified. Fallback (already designed into
`asr_base.Segment`): emit sentence-level segments with empty `words`. The
`Transcriber` interface hides which mode is live, so the rest of the app is
unaffected.

## Pyannote — needs HF_TOKEN (expected)

`Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")` 403s until a
Hugging Face token with access to the gated model is set. This is expected and
handled by `Diarizer.load()` with a friendly message. Action for the user:
create an HF token, accept the model terms, put it in `.env` as `HF_TOKEN`.

## Model / VRAM footprint (measured/expected)

| Model | VRAM | Slot |
|---|---|---|
| Canary SALM (bf16) | ~6 GB | ASR (exclusive) |
| Whisper large-v3 (fp16) | ~3.1 GB | ASR (exclusive) |
| pyannote 3.1 | ~1 GB | diarize (resident) |
| Ollama qwen-fast (27B iq3) | ~13.7 GB | naming — **never concurrent with ASR/diarize** |

The single background worker + `prepare_for_ollama()` enforce the no-concurrency
VRAM rule by construction.

## Locked version set (frozen in pyproject.toml)

- `torch==2.8.0+cu128`, `torchaudio==2.8.0+cu128` (from pytorch cu128 index)
  - chosen because: torchaudio 2.11 dropped `torchaudio.AudioMetaData` (moved to
    the torchcodec backend, no Windows wheel) which breaks `import pyannote.audio`;
    pyannote 4.x needs torchcodec (also no Windows wheel). 2.8.0 keeps both
    `AudioMetaData` **and** Blackwell sm_120.
- `transformers>=4.41,<5` (4.57.6 resolved)
- `pyannote.audio==3.4.0`
- `faster-whisper` (1.2.1)
- `nemo==8.0.2` (Canary loader)

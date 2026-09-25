# media-transcription

A local-network transcription service: any device on the LAN opens a web UI,
uploads audio or video, and gets back a speaker-labeled, named transcript. The
browser extracts the audio track first (a 5 GB video uploads as ~100 MB of
16 kHz mono WAV); anything it can't decode (mkv/avi/wmv, files over 500 MB)
uploads raw and the server strips the audio with ffmpeg. Per job the pipeline
is: normalize to 16 kHz WAV → ASR (you pick per job) → pyannote speaker
diarization → optional Ollama pass that assigns real names → TXT/SRT/VTT/JSON
outputs. One uvicorn process serves the API and the built web UI on
`0.0.0.0:8000`.

## Hardware note

Built for a single RTX 5080 (16 GB VRAM). All models share that VRAM, so the
app enforces by construction that **Ollama (name inference) never runs at the
same time as ASR or diarization**: the single background worker unloads the ASR
model before the naming stage, and only one ASR backend is ever resident.

| Model | VRAM | Loaded when |
|---|---|---|
| Canary qwen-2.5b (bf16) | ~6 GB | transcribing (exclusive slot) |
| Whisper large-v3 (fp16) | ~3.1 GB | transcribing (exclusive slot) |
| pyannote speaker-diarization-3.1 | ~1 GB | diarizing (kept resident) |
| Ollama naming model (e.g. a 27B GGUF) | ~13.7 GB | naming — never overlaps ASR/diarize |

## Prerequisites

- Python via [uv](https://docs.astral.sh/uv/) (uv manages a `.venv` with Python 3.12)
- Node 20+ (web build)
- ffmpeg on `PATH` (e.g. `winget install Gyan.FFmpeg`) — the server uses
  `ffmpeg`/`ffprobe` to strip and normalize audio
- [Ollama](https://ollama.com) running on `localhost:11434` with at least one
  model installed (used for speaker naming; jobs still complete without it —
  speakers just keep their `Speaker N` labels). The upload form lists every
  model Ollama has and lets you pick one per job; the default is the
  `OLLAMA_MODEL` value in `.env` (currently `qwen-fast`).
- A Hugging Face token with access to the gated
  [`pyannote/speaker-diarization-3.1`](https://huggingface.co/pyannote/speaker-diarization-3.1):
  accept the model's terms on that page, then create a token at
  <https://huggingface.co/settings/tokens>

## Setup

```powershell
uv sync
cd web
npm install
cd ..
Copy-Item .env.example .env
# edit .env: set HF_TOKEN=hf_... (see .env.example for everything else)
```

## Preload models (first time only)

```powershell
.venv\Scripts\python scripts\preload_models.py
```

Downloads everything once (~9 GB: canary ~5.5 GB, Whisper large-v3 ~3.1 GB,
pyannote ~1 GB) into the Hugging Face cache (`~/.cache/huggingface` on Windows)
and prints progress per model. Each step is independent, so one failure (e.g.
missing `HF_TOKEN`) doesn't stop the others. The app would download the same
files on first use anyway — this just does it up front with clearer output.

## Run

```powershell
scripts\run.ps1
```

The script prepends the CUDA 12.9 runtime to `PATH` (Whisper's ctranslate2
backend needs those DLLs), rebuilds `web/dist` if it's older than `web/src`,
and launches uvicorn. When it's up it prints the addresses:

- this machine: `http://localhost:8000`
- other devices on your LAN: the printed IP, e.g. `http://192.168.1.20:8000`

## Using it

1. Upload a file (audio or video, any format with an audio track). If the
   browser can decode it, only the audio is uploaded; otherwise the whole file
   goes up and the server strips audio with ffmpeg.
2. Pick the ASR backend:
   - **English (recommended)** — `nvidia/canary-qwen-2.5b`. Fast and accurate
     for English (and accents); no other languages.
   - **Multilingual** — Whisper large-v3, with an optional language hint
     (leave empty to auto-detect).
3. Toggles and options, all on by default:
   - **Diarize** — separate speakers with pyannote.
   - **Name speakers** — Ollama pass that assigns real names where a speaker
     says their name; everyone else stays `Speaker N`.
   - **Ollama model** — which model does the naming pass (dropdown lists every
     model on your Ollama server). Leave it on `(default)` to use `OLLAMA_MODEL`
     from `.env`.
4. Watch the job list — stages (extract → transcribe → diarize → name → write)
   and progress update live over SSE. Jobs can be cancelled between stages.
5. When done: read the transcript in the UI (colored speaker chips, names with
   evidence tooltips) and download **TXT / SRT / VTT / JSON** (SRT/VTT are
   merged, speaker-prefixed subtitle lines; JSON is the full canonical
   transcript).

## Data layout

Everything the service writes lives under `data/` (gitignored):

```
data/uploads/<job_id>/…     # spooled uploads + the 16 kHz working WAV
data/outputs/<job_id>.{json,txt,srt,vtt}
data/transcription.db       # job history (SQLite)
```

Set `DATA_DIR` in `.env` to move it. **This repo lives in a OneDrive-synced
folder — exclude `data/` from OneDrive backup (or point `DATA_DIR` at a
non-synced drive) before it starts holding gigabytes of uploads.**

## Troubleshooting

- **Hugging Face 403 / "gated" error** — `HF_TOKEN` is missing, lacks read
  access, or the model terms weren't accepted. Accept the terms at
  `huggingface.co/pyannote/speaker-diarization-3.1` and check the token in
  `.env`.
- **"No audio track found" job error** — the uploaded file has no audio
  stream (empty video, image, …). There's nothing to transcribe.
- **CUDA out of memory** — close other GPU apps (games, browsers with
  hardware acceleration, other Ollama loads). The app never runs two ASR
  models at once, but a 27B Ollama model leaves little room: see the VRAM
  table above.
- **ctranslate2 / CUDA DLL load failure** (Whisper) — the CUDA 12.9 runtime
  bin must be on `PATH`. `scripts\run.ps1` prepends it; if you launch uvicorn
  by hand, add `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9\bin`
  yourself.
- **Ollama unreachable** — naming degrades gracefully: the job completes with
  `Speaker N` labels instead of real names. Start Ollama (or fix `OLLAMA_URL`
  in `.env`) and re-run if you want names.
- **Port 8000 in use** — find the other listener (`Get-NetTCPConnection
  -LocalPort 8000`) and stop it, or change the `--port` in `scripts\run.ps1`.

## Development

Two terminals:

```powershell
# API with hot reload
.venv\Scripts\python -m uvicorn server.app.main:app --reload --port 8000

# web frontend with HMR (Vite dev server on :5173)
cd web
npm run dev
```

The Vite dev server proxies `/api` to `localhost:8000`
(see `web/vite.config.ts`), so the UI behaves identically in dev. Tests:
`.venv\Scripts\python -m pytest server/tests -q` from the project root.

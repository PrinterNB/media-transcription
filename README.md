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

Install each of these (Windows PowerShell):

1. **[uv](https://docs.astral.sh/uv/)** — manages the project `.venv` with
   Python 3.12:

   ```powershell
   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

   (Alternative: `winget install astral-sh.uv`.) The installer puts `uv.exe`
   in `C:\Users\<you>\.local\bin` and adds it to `PATH` — open a new terminal
   afterwards.
2. **Node 20+** (web build): `winget install OpenJS.NodeJS.LTS`. Check with
   `node --version`.
3. **ffmpeg** — the server uses `ffmpeg`/`ffprobe` to strip and normalize
   audio. `winget install Gyan.FFmpeg` is the self-contained option; Chocolatey
   (`choco install ffmpeg`) works too if you already use it. Either way
   `ffmpeg.exe` must resolve on `PATH` (`ffmpeg -version`).
4. **[Ollama](https://ollama.com)** (speaker naming) —
   `winget install Ollama.Ollama` (or download from ollama.com); it runs on
   `localhost:11434` by default. Pull at least one model, e.g.
   `ollama pull qwen-fast` — any model you pull works: the upload form lists
   every model Ollama has and lets you pick one per job, and the default is the
   `OLLAMA_MODEL` value in `.env` (currently `qwen-fast`). If Ollama is offline,
   jobs still complete — speakers just keep their `Speaker N` labels.
5. **A Hugging Face token** with access to the gated pyannote models.
   Speaker diarization needs **two** gated repos, and you must accept the
   terms on **both** pages (each has its own acceptance button):

   1. [`pyannote/speaker-diarization-3.1`](https://huggingface.co/pyannote/speaker-diarization-3.1)
   2. [`pyannote/segmentation-3.0`](https://huggingface.co/pyannote/segmentation-3.0)
      (the segmentation model the diarization pipeline downloads internally)

   Then create a token at <https://huggingface.co/settings/tokens> and put it
   in `.env` as `HF_TOKEN=hf_...`. If you've only accepted one of the two
   repos, the job fails with `Hugging Face 403 / "gated"` (or the cryptic
   `'NoneType' object has no attribute 'eval'`) — see Troubleshooting.

## Setup

```powershell
uv sync
cd web
npm install
cd ..
Copy-Item .env.example .env
# edit .env: set HF_TOKEN=hf_... (see .env.example for everything else)
```

## Models (~9 GB, one time)

The app needs three model families, ~9 GB total (canary ~5.5 GB, Whisper
large-v3 ~3.1 GB, pyannote ~1 GB). Install them either with the preload
script (**Option A**) or by downloading the files yourself (**Option B**).
You can also mix them — every model resolves independently, so a manual
canary plus a script-downloaded whisper works fine. When a model's folder
exists under `models/` in the project root (or `MODELS_DIR` from `.env`, if
you set it), the app uses that folder automatically — no other configuration
needed. `models/` is gitignored.

### Option A — preload script

```powershell
.venv\Scripts\python scripts\preload_models.py
```

Downloads everything once into the Hugging Face cache
(`C:\Users\<you>\.cache\huggingface` on Windows) and prints progress per
model. Each step is independent, so one failure (e.g. missing `HF_TOKEN`)
doesn't stop the others. The app would download the same files on first use
anyway — this just does it up front with clearer output.

To check what's already local without touching the network (e.g. an
air-gapped machine):

```powershell
.venv\Scripts\python scripts\preload_models.py --local-only
```

**`[WinError 1314] A required privilege is not held by the client`** is a
Windows file-lock/privilege glitch in huggingface_hub when it moves a fresh
download into the cache. The script already retries these, clearing the
partial cache snapshot between attempts. If it still fails, delete the
partially-filled cache folder and re-run, e.g.
`C:\Users\<you>\.cache\huggingface\hub\models--Systran--faster-whisper-large-v3`
(or whichever `models--*` folder was being written when it stopped).

### Option B — download the files yourself

Create `models/` in the project root with one subfolder per model. All three
repos are plain file downloads from Hugging Face (a free account covers all
of them; the pyannote ones additionally need the accept-terms click and a
`HF_TOKEN`):

- **Canary qwen-2.5b** → `models\canary-qwen-2.5b\` — from
  [nvidia/canary-qwen-2.5b](https://huggingface.co/nvidia/canary-qwen-2.5b).
  The whole repo is two files (~5.1 GB): `config.json` +
  `model.safetensors`. Note: on first load NeMo also fetches the small
  (~16 MB) Qwen tokenizer files it references, so a manual canary install
  still needs the network once (they're cached after that).
- **Whisper large-v3** → `models\faster-whisper-large-v3\` — from
  [Systran/faster-whisper-large-v3](https://huggingface.co/Systran/faster-whisper-large-v3).
  All five files: `model.bin`, `config.json`, `tokenizer.json`,
  `vocabulary.json`, `preprocessor_config.json`.
- **pyannote speaker-diarization-3.1** →
  `models\pyannote-speaker-diarization-3.1\` — from
  [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1).
  This one is **gated**: log in to Hugging Face and click *Agree and
  continue* on the repo page first, then copy the whole repo (a handful of
  KB: `config.yaml` + `handler.py`). Note the repo is just the pipeline
  config — on first load the ~1 GB of underlying model files it references
  are still downloaded from the hub (cached after that), and the segmentation
  model (`pyannote/segmentation-3.0`) is **gated too**: accept its terms as
  well and keep a valid `HF_TOKEN` in `.env`.

The preload script picks manual installs up too: it loads them to verify and
skips the corresponding download.

## Run

```powershell
scripts\run.ps1
```

The script prepends the CUDA 12.9 runtime to `PATH` (Whisper's ctranslate2
backend needs those DLLs), rebuilds `web/dist` if it's older than `web/src`,
and launches uvicorn. When it's up it prints the addresses:

- this machine: `http://localhost:8000`
- other devices on your LAN: the printed IP, e.g. `http://192.168.1.20:8000`

## Users & admin

Everything after the login screen is per-user. Every `/api` route requires a
signed-in user (except `/api/health`, `/api/ollama/models`, and
`/api/summary/templates`). Passwords are argon2-hashed; a session is a signed
HttpOnly cookie (`SameSite=Lax`, 30 days).

- **First boot** seeds the admin account from `.env`: `ADMIN_USERNAME`
  (default `admin`) and `ADMIN_PASSWORD` (default `admin` — change it). `.env`
  only fixes the password at *creation*; a password later changed in the admin
  panel wins and survives restarts.
- **Sign-in / sign-up** — the login screen is the entry point. "Add user"
  creates an account (username 3–32 chars of `A-Za-z0-9._-`, password 8+
  chars) and signs you straight in. By default sign-ups are active at once;
  with approval required (Data tab, below), they start as *pending* and can't
  log in until an admin approves them.
- **Per-user ownership** — every job belongs to the user who created it, and
  the main list shows only your own jobs (someone else's 404s on get/download/
  stream). You can delete your own jobs — per-job delete button, or "Delete my
  jobs" from the sidebar — but a job that's still running must be cancelled
  first (409). Jobs from before auth existed were backfilled to the admin
  account.
- **Admin panel** — admins (only) see an "Admin panel" button in the top bar,
  with three tabs:
  - **Users** — every account (role, status, last login, job count, tokens);
    promote/demote admin, approve pending / enable / disable, set or reset
    passwords, delete a user (removes their jobs + files; you can't delete
    yourself). The "Add user" form here bypasses the approval requirement —
    it's direct provisioning.
  - **Data** — the "Require approval for new sign-ups" toggle (persisted,
    takes effect immediately); a table of **all** users' jobs with per-row
    delete; "Delete all data" — the old wipe, now admin-only, and it 409s if
    any job is still running.
  - **Usage** — per-user and totals: job count, bytes uploaded, prompt +
    completion tokens (captured from Ollama's `prompt_eval_count` /
    `eval_count` on naming, summarization, and chat calls, stored per job),
    and transcript duration.

New `.env` vars (all in `.env.example`): `ADMIN_USERNAME=admin`,
`ADMIN_PASSWORD=admin` (change me), `SESSION_SECRET=` (blank = auto-generated
once and stored in the database), and `REQUIRE_APPROVAL=false` — if `true`,
that's the *initial* value of the approval toggle; the admin panel toggle
then persists its own value.

Security posture: this is a LAN-trusted app — no rate limiting and plain-HTTP
cookies (no `Secure` flag). Exposing it beyond the LAN? Put it behind HTTPS
and set `Secure` cookies.

## Using it

1. Sign in (or create an account — see Users & admin).
2. Upload a file (audio or video, any format with an audio track). If the
   browser can decode it, only the audio is uploaded; otherwise the whole file
   goes up and the server strips audio with ffmpeg.
3. Pick the ASR backend:
   - **English (recommended)** — `nvidia/canary-qwen-2.5b`. Fast and accurate
     for English (and accents); no other languages.
   - **Multilingual** — Whisper large-v3, with an optional language hint
     (leave empty to auto-detect).
4. Toggles and options, all on by default:
   - **Diarize** — separate speakers with pyannote.
   - **Name speakers** — Ollama pass that assigns real names where a speaker
     says their name; everyone else stays `Speaker N`.
   - **Ollama model** — which model does the naming pass (dropdown lists every
     model on your Ollama server). Leave it on `(default)` to use `OLLAMA_MODEL`
     from `.env`.
5. Watch the job list — stages (extract → transcribe → diarize → name → write)
   and progress update live over SSE. Jobs can be cancelled between stages.
6. When done: read the transcript in the UI (colored speaker chips, names with
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
  access, or the model terms weren't accepted. The diarizer needs **both**
  gated repos accepted: `huggingface.co/pyannote/speaker-diarization-3.1`
  **and** `huggingface.co/pyannote/segmentation-3.0`, then check the token
  in `.env`. A missing second repo shows up as `'NoneType' object has no
  attribute 'eval'` (pyannote swallows the 403 and returns `None`).
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

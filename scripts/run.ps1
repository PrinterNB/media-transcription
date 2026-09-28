# scripts/run.ps1 -- production launcher for media-transcription.
#
#   - prepends the CUDA 12.9 runtime bin to PATH (faster-whisper's ctranslate2
#     links against its DLLs and needs them findable at import time)
#   - sets PYTHONUTF8=1 (Windows UTF-8: console + Python text I/O)
#   - creates the .venv with `uv sync` on first run, and keeps it in sync with
#     uv.lock afterwards (fast no-op when already current)
#   - creates .env from .env.example on first run
#   - builds web/dist if missing or older than anything under web/src
#   - launches uvicorn (no reload) serving API + web UI on 0.0.0.0:8000
#     (main.py prints the LAN IP + a QR code at boot)
#
# Run from anywhere:  scripts\run.ps1   (or just double-click run.cmd)

$ErrorActionPreference = "Stop"

# CUDA 12.9 runtime bin directory. faster-whisper (ctranslate2) needs the CUDA
# 12.9 DLLs (cudart64_12.dll, cublas64_12.dll, ...) from here on PATH.
# Adjust this if your CUDA 12.9 toolkit lives somewhere else.
$Cuda129Bin = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9\bin"
if (-not (Test-Path $Cuda129Bin)) {
    Write-Warning "CUDA 12.9 bin not found at '$Cuda129Bin' - faster-whisper may fail to load the CUDA runtime. Fix the path at the top of this script."
} else {
    $env:PATH = "$Cuda129Bin;$env:PATH"
}

# Windows UTF-8 (plan: keep every text path in UTF-8)
$env:PYTHONUTF8 = "1"

$Root = Split-Path -Parent $PSScriptRoot
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"

Push-Location $Root
try {
    # --- python venv: create on first run, refresh otherwise -----------------
    # A .venv is always regenerable from uv.lock, so this section is free to
    # rebuild one that is missing or half-installed.
    $haveUv = $null -ne (Get-Command uv -ErrorAction SilentlyContinue)
    $VenvDir = Join-Path $Root ".venv"
    if (-not $haveUv -and -not (Test-Path $VenvPy)) {
        Write-Error @"
No virtualenv at '$VenvPy' and 'uv' is not on PATH, so the launcher cannot
create one. First-time setup, run these from the project root, then run this
launcher again:

  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"   # install uv
  uv sync                     # install Python dependencies
  Copy-Item .env.example .env # then edit .env (at minimum HF_TOKEN)
"@
        exit 1
    }

    if ($haveUv) {
        # uv normally hardlinks the installed files into the venv, but
        # hardlinks fail with "The cloud operation cannot be performed on a
        # file with incompatible hardlinks" when the repo sits in a
        # OneDrive/cloud-managed folder (e.g. an unzipped download left in
        # Downloads) - and a failed hardlink leaves packages only
        # half-installed. Copy instead: only the first install is slower.
        $env:UV_LINK_MODE = "copy"

        # Fast no-op when the venv already matches uv.lock.
        uv sync
        if ($LASTEXITCODE -ne 0 -and (Test-Path $VenvDir)) {
            Write-Warning "uv sync failed (exit code $LASTEXITCODE) - the .venv may be half-installed. Deleting it and retrying once..."
            Remove-Item $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
            uv sync
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Error @"
uv sync failed (exit code $LASTEXITCODE) - see output above. The app cannot
start without its Python dependencies. If it keeps failing, delete the .venv
folder and run this launcher again; otherwise report the error above.
"@
            exit 1
        }
    } else {
        Write-Warning "uv not on PATH - skipping 'uv sync' (the .venv may be stale; run 'uv sync' to refresh it)."
    }

    # --- .env: start from .env.example on first run ---------------------------
    if (-not (Test-Path ".env")) {
        if (Test-Path ".env.example") {
            Copy-Item ".env.example" ".env"
            Write-Host "Created .env from .env.example - the default login is admin/admin; add your HF_TOKEN before diarization will work."
        } else {
            Write-Warning "No .env (and no .env.example) - running with built-in defaults."
        }
    }

    # --- install web deps if this is a fresh checkout ------------------------
    if (-not (Test-Path "web\node_modules")) {
        Write-Host "Installing web dependencies (npm install)..."
        Push-Location "web"
        try {
            npm.cmd install
            if ($LASTEXITCODE -ne 0) {
                throw "npm install failed (exit code $LASTEXITCODE)"
            }
        } finally {
            Pop-Location
        }
    }

    # --- build the web frontend if stale -------------------------------------
    $needBuild = $true
    if (Test-Path "web\dist") {
        $srcNewest = (Get-ChildItem "web\src" -Recurse -File |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime
        $distNewest = (Get-ChildItem "web\dist" -Recurse -File |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime
        $needBuild = $srcNewest -gt $distNewest
    }
    if ($needBuild) {
        Write-Host "Building web frontend (npm run build)..."
        Push-Location "web"
        try {
            npm.cmd run build
            if ($LASTEXITCODE -ne 0) {
                throw "npm run build failed (exit code $LASTEXITCODE)"
            }
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "web\dist is up to date."
    }

    # --- launch (no --reload in prod) ---------------------------------------
    # uvicorn is started through its console entry point (uvicorn.main:main)
    # via the venv's python, because the two "normal" ways are both flaky:
    # `python -m uvicorn` needs a __main__.py that not every uvicorn version
    # ships, and the venv's uvicorn.exe launcher is a uv "trampoline" that
    # fails ("uv trampoline failed to canonicalize script path") on some
    # Windows setups - see astral-sh/uv#17341.
    Write-Host "Starting media-transcription on 0.0.0.0:8000 (Ctrl+C to stop)..."
    & $VenvPy -c "from uvicorn.main import main; main()" server.app.main:app --host 0.0.0.0 --port 8000
    if ($LASTEXITCODE -ne 0) {
        Write-Error "uvicorn exited with code $LASTEXITCODE"
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}

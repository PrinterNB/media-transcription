# scripts/run.ps1 -- production launcher for media-transcription.
#
#   - prepends the CUDA 12.9 runtime bin to PATH (faster-whisper's ctranslate2
#     links against its DLLs and needs them findable at import time)
#   - sets PYTHONUTF8=1 (Windows UTF-8: console + Python text I/O)
#   - builds web/dist if missing or older than anything under web/src
#   - launches uvicorn (no reload) serving API + web UI on 0.0.0.0:8000
#     (main.py prints the LAN IP at boot)
#
# Run from anywhere:  scripts\run.ps1

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
if (-not (Test-Path $VenvPy)) {
    Write-Error "No virtualenv at '$VenvPy'. Run 'uv sync' from the project root first."
    exit 1
}

Push-Location $Root
try {
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
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) {
            throw "npm run build failed (exit code $LASTEXITCODE)"
        }
    } else {
        Write-Host "web\dist is up to date."
    }

    # --- launch (no --reload in prod) ---------------------------------------
    Write-Host "Starting media-transcription on 0.0.0.0:8000 (Ctrl+C to stop)..."
    & $VenvPy -m uvicorn server.app.main:app --host 0.0.0.0 --port 8000
    if ($LASTEXITCODE -ne 0) {
        Write-Error "uvicorn exited with code $LASTEXITCODE"
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}

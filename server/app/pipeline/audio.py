"""ffmpeg audio normalization -> canonical 16 kHz mono s16 WAV.

Every downstream stage (ASR, diarization, naming) consumes `audio_16k.wav`.
This is the server-side half of the audio contract: the browser already sent a
16 kHz mono WAV when it could, but anything it couldn't decode (mkv/avi/wmv,
>500 MB) arrives raw and gets stripped here with ffmpeg — so ANY file type
with an audio track works.

Uses an argument-list subprocess (no shell) and reads ffmpeg's
`-progress pipe:1` for duration-based progress.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable

ProgressCB = Callable[[float, str], None]


class AudioError(Exception):
    pass


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise AudioError(
            "ffmpeg not found on PATH. Install it (e.g. `winget install Gyan.FFmpeg`) "
            "and make sure it's on PATH."
        )


def ffprobe_duration(path: Path) -> float:
    """Return media duration in seconds via ffprobe (no shell)."""
    if shutil.which("ffprobe") is None:
        raise AudioError("ffprobe not found on PATH (ships with ffmpeg).")
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise AudioError(f"ffprobe failed: {out.stderr.strip()[:300]}")
    try:
        return float(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0.0


def _has_audio_stream(path: Path) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return bool(out.stdout.strip())


def probe_props(path: Path) -> dict:
    """Return {sample_rate, channels, duration} for the first audio stream."""
    if shutil.which("ffprobe") is None:
        raise AudioError("ffprobe not found on PATH (ships with ffmpeg).")
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate,channels",
         "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise AudioError(f"ffprobe failed: {out.stderr.strip()[:300]}")
    import json as _json
    try:
        data = _json.loads(out.stdout or "{}")
    except _json.JSONDecodeError:
        raise AudioError(f"ffprobe returned no JSON: {out.stdout[:200]}")
    streams = data.get("streams") or []
    st = streams[0] if streams else {}
    fmt = data.get("format", {})
    return {
        "sample_rate": _as_int(st.get("sample_rate")),
        "channels": _as_int(st.get("channels")),
        "duration": _as_float(fmt.get("duration")),
    }


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _as_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def normalize(src: Path, dst: Path, progress_cb: ProgressCB | None = None) -> float:
    """Produce a 16 kHz mono s16 WAV at `dst`. Returns duration in seconds.

    If `src` is already 16 kHz mono s16 (the browser-extracted case) we could
    `-c copy`, but a straight re-encode is cheap and guarantees the contract,
    so we always re-encode the audio stream.
    """
    _require_ffmpeg()
    if not src.exists():
        raise AudioError(f"input not found: {src}")
    if not _has_audio_stream(src):
        raise AudioError(
            "No audio track found in that file. It must contain audio to "
            "transcribe."
        )

    duration = ffprobe_duration(src)
    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-progress", "pipe:1",
        "-i", str(src),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(dst),
    ]
    # Stream the progress. stderr MUST be drained concurrently in a thread:
    # ffmpeg writes its banner (~6 KB on current builds) to stderr early, and
    # if we only read it after proc.wait() the pipe fills and ffmpeg blocks
    # on a write nobody is consuming — the job hangs at 0% CPU forever.
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    assert proc.stdout is not None and proc.stderr is not None
    stderr_chunks: list[str] = []

    def _drain_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_chunks.append(line)

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()
    out_time_ms = 0.0
    for line in proc.stdout:
        m = re.search(r"out_time_ms=(\d+)", line)
        if m:
            raw = int(m.group(1))
            # Named "ms", but current ffmpeg builds fill it with microseconds;
            # the ffprobe duration lets us tell the two apart.
            t = raw / 1_000.0
            if duration > 0 and t > duration and raw >= duration:
                t = raw / 1_000_000.0
            out_time_ms = t
            if progress_cb and duration > 0:
                progress_cb(min(1.0, out_time_ms / duration), f"extracting {out_time_ms:.0f}s")
    proc.stdout.close()
    stderr_thread.join()
    proc.wait()
    if proc.returncode != 0 or not dst.exists():
        # tail, not head: ffmpeg's banner is at the front, the actual error
        # message is at the end of stderr.
        err = "".join(stderr_chunks).strip()
        raise AudioError(f"ffmpeg failed (code {proc.returncode}): {err[-500:]}")

    if progress_cb:
        progress_cb(1.0, "extract done")
    # re-read final duration from the produced wav (authoritative)
    final = ffprobe_duration(dst)
    return final or duration

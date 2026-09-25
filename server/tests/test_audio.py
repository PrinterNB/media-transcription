"""Audio: ffmpeg normalize -> canonical 16 kHz mono s16 WAV.

Needs ffmpeg (and ffprobe, which ships with it) on PATH; skipped otherwise.
"""
import math
import shutil
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.app.pipeline import audio  # noqa: E402

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)


def _write_wav(path: Path, rate: int, channels: int, seconds: float,
               freq: float = 440.0) -> None:
    """Write a short sine WAV with the stdlib wave module (16-bit PCM)."""
    n = int(rate * seconds)
    frames = bytearray()
    for i in range(n):
        sample = int(0.3 * 32767 * math.sin(2 * math.pi * freq * i / rate))
        for _ in range(channels):
            frames += sample.to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


def _wav_props(path: Path) -> tuple:
    with wave.open(str(path), "rb") as w:
        return w.getframerate(), w.getnchannels(), w.getsampwidth()


def test_normalize_resamples_to_16k_mono_s16(tmp_path):
    # 44100 Hz stereo input must come out as 16000 Hz mono 16-bit.
    src = tmp_path / "in.wav"
    _write_wav(src, rate=44100, channels=2, seconds=0.5)
    dst = tmp_path / "audio_16k.wav"

    duration = audio.normalize(src, dst)

    assert dst.exists()
    rate, channels, width = _wav_props(dst)
    assert rate == 16000
    assert channels == 1
    assert width == 2  # 16-bit PCM
    assert duration > 0.3  # ~0.5 s of audio survived


def test_normalize_already_16k_mono(tmp_path):
    # The browser-extracted case: input already at 16k mono must still
    # round-trip to a valid 16 kHz mono s16 WAV.
    src = tmp_path / "in.wav"
    _write_wav(src, rate=16000, channels=1, seconds=0.5)
    dst = tmp_path / "out.wav"

    duration = audio.normalize(src, dst)

    assert _wav_props(dst) == (16000, 1, 2)
    assert duration > 0.3


def test_normalize_reports_progress(tmp_path):
    src = tmp_path / "in.wav"
    _write_wav(src, rate=44100, channels=2, seconds=0.5)
    calls: list = []

    audio.normalize(src, tmp_path / "out.wav",
                    lambda frac, msg: calls.append((frac, msg)))

    assert calls, "progress callback never fired"
    assert calls[-1][0] == 1.0  # ends at 100%


def test_normalize_without_audio_stream_raises(tmp_path):
    # A text file is not a media file at all, but it must raise the job-level
    # AudioError, not some subprocess/ffprobe traceback.
    src = tmp_path / "notes.txt"
    src.write_text("no audio in here\n", encoding="utf-8")

    with pytest.raises(audio.AudioError, match="No audio track"):
        audio.normalize(src, tmp_path / "out.wav")

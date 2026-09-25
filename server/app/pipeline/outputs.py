"""Canonical transcript JSON + TXT / SRT / VTT writers.

The JSON is the source of truth; the other three are derived from it. SRT and
VTT are written as `utf-8-sig` (BOM) so Windows players/Notepad show them
correctly.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..models.asr_base import Segment


# ---------- canonical JSON ----------
def build_canonical(
    job_id: str,
    source: str,
    duration: float,
    speaker_map: dict,
    segments: list[Segment],
) -> dict:
    return {
        "job_id": job_id,
        "source": source,
        "duration": round(duration, 3),
        "speakers": speaker_map,
        "segments": [s.to_dict() for s in segments],
    }


# ---------- formatting helpers ----------
def _ts_srt(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ts_vtt(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _ts_txt(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _label(speaker: str | None, speaker_map: dict) -> str:
    if not speaker or speaker == "SPEAKER_UNKNOWN":
        return speaker_map.get(speaker, {}).get("name") or "Speaker"
    name = speaker_map.get(speaker, {}).get("name")
    if name:
        return name
    # "SPEAKER_02" -> "Speaker 2"
    import re as _re
    m = _re.search(r"(\d+)$", speaker)
    return f"Speaker {int(m.group(1))}" if m else "Speaker"


# ---------- writers ----------
def write_txt(segments: list[Segment], speaker_map: dict, path: Path) -> None:
    lines = []
    for s in segments:
        if not s.text:
            continue
        lines.append(f"{_ts_txt(s.start)}  {_label(s.speaker, speaker_map)}: {s.text}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_srt(segments: list[Segment], speaker_map: dict, path: Path) -> None:
    out = []
    idx = 1
    prev_spk = None
    for s in segments:
        if not s.text:
            continue
        label = _label(s.speaker, speaker_map)
        prefix = f"{label}: " if (s.speaker != prev_spk) else ""
        out.append(f"{idx}\n{_ts_srt(s.start)} --> {_ts_srt(s.end)}\n{prefix}{s.text}\n")
        prev_spk = s.speaker
        idx += 1
    path.write_text("\n".join(out), encoding="utf-8-sig")


def write_vtt(segments: list[Segment], speaker_map: dict, path: Path) -> None:
    out = ["WEBVTT", ""]
    prev_spk = None
    for s in segments:
        if not s.text:
            continue
        label = _label(s.speaker, speaker_map)
        prefix = f"{label}: " if (s.speaker != prev_spk) else ""
        out.append(f"{_ts_vtt(s.start)} --> {_ts_vtt(s.end)}\n{prefix}{s.text}\n")
        prev_spk = s.speaker
    # VTT must start at byte 0 (strict parsers reject a BOM), so no BOM here.
    path.write_text("\n".join(out), encoding="utf-8")


def write_all(
    out_dir: Path,
    job_id: str,
    source: str,
    duration: float,
    speaker_map: dict,
    segments: list[Segment],
) -> dict:
    """Write all four formats; return {fmt: path}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    canonical = build_canonical(job_id, source, duration, speaker_map, segments)
    paths = {
        "json": out_dir / f"{job_id}.json",
        "txt": out_dir / f"{job_id}.txt",
        "srt": out_dir / f"{job_id}.srt",
        "vtt": out_dir / f"{job_id}.vtt",
    }
    import json as _json
    paths["json"].write_text(_json.dumps(canonical, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    write_txt(segments, speaker_map, paths["txt"])
    write_srt(segments, speaker_map, paths["srt"])
    write_vtt(segments, speaker_map, paths["vtt"])
    return {k: str(v) for k, v in paths.items()}

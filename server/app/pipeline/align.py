"""Assign speaker labels to ASR segments by temporal overlap with diarization
tracks, then merge consecutive same-speaker segments into readable subtitle
lines.

Rule: each ASR segment takes the speaker whose track(s) overlap it the most.
If the winning overlap is < 30% of the segment's duration we call it
SPEAKER_UNKNOWN (better "Unknown" than a confident-wrong name). The full
per-segment overlap map is preserved for debugging/UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models.asr_base import Segment
from ..models.diarize import DiarizationTrack

UNKNOWN = "SPEAKER_UNKNOWN"
_MIN_OVERLAP_FRAC = 0.30
# Merge consecutive same-speaker lines up to this many seconds so subtitles
# aren't one word per line.
_MERGE_MAX_SEC = 20.0


def overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


@dataclass
class _Acc:
    start: float
    speaker: str
    parts: list = field(default_factory=list)
    end: float = 0.0

    @property
    def text(self) -> str:
        return " ".join(self.parts).strip()


def assign_and_merge(
    segments: list[Segment],
    tracks: list[DiarizationTrack],
) -> list[Segment]:
    if not tracks:
        return segments

    # Precompute per-speaker track list for quick overlap queries.
    by_speaker: dict[str, list[tuple[float, float]]] = {}
    for t in tracks:
        by_speaker.setdefault(t.speaker, []).append((t.start, t.end))

    # ---- pass 1: assign speaker ----
    for seg in segments:
        span = max(1e-6, seg.end - seg.start)
        best_spk, best_ov = UNKNOWN, 0.0
        for spk, spans in by_speaker.items():
            ov = sum(overlap(seg.start, seg.end, a, b) for a, b in spans)
            if ov > best_ov:
                best_ov, best_spk = ov, spk
        seg.speaker = best_spk if best_ov >= _MIN_OVERLAP_FRAC * span else UNKNOWN

    # ---- pass 2: merge consecutive same-speaker into <= _MERGE_MAX_SEC lines
    merged: list[Segment] = []
    for seg in segments:
        spk = seg.speaker or UNKNOWN
        if (
            merged
            and merged[-1].speaker == spk
            and (seg.end - merged[-1].start) <= _MERGE_MAX_SEC
        ):
            merged[-1].end = seg.end
            if seg.text:
                merged[-1].text = (merged[-1].text + " " + seg.text).strip()
            merged[-1].words = (merged[-1].words or []) + (seg.words or [])
        else:
            merged.append(Segment(
                start=seg.start, end=seg.end, text=seg.text,
                speaker=seg.speaker, words=list(seg.words or []),
            ))
    return merged

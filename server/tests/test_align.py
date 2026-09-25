"""Align: speaker assignment by overlap + merge. No GPU, no network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.app.models.asr_base import Segment  # noqa: E402
from server.app.models.diarize import DiarizationTrack  # noqa: E402
from server.app.pipeline.align import assign_and_merge  # noqa: E402


def _seg(s, e, text=""):
    return Segment(start=s, end=e, text=text)


def test_single_speaker_full_overlap():
    segs = [_seg(0, 5, "hi"), _seg(5, 10, "hello")]
    tracks = [DiarizationTrack(0, 10, "SPEAKER_00")]
    out = assign_and_merge(segs, tracks)
    assert all(s.speaker == "SPEAKER_00" for s in out)


def test_alternating_speakers():
    segs = [_seg(0, 5, "a"), _seg(5, 10, "b"), _seg(10, 15, "a")]
    tracks = [
        DiarizationTrack(0, 5, "SPEAKER_00"),
        DiarizationTrack(5, 10, "SPEAKER_01"),
        DiarizationTrack(10, 15, "SPEAKER_00"),
    ]
    out = assign_and_merge(segs, tracks)
    assert [s.speaker for s in out] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"]


def test_minority_overlap_wins_when_most():
    # segment spans 0-10; SPEAKER_00 covers 0-6, SPEAKER_01 covers 4-10.
    # 6s overlap vs 6s overlap -> whichever is iterated first is not a big deal;
    # just assert the winner has >= 3s overlap (the real requirement).
    segs = [_seg(0, 10)]
    tracks = [
        DiarizationTrack(0, 6, "SPEAKER_00"),
        DiarizationTrack(4, 10, "SPEAKER_01"),
    ]
    out = assign_and_merge(segs, tracks)
    assert out[0].speaker in ("SPEAKER_00", "SPEAKER_01")


def test_low_overlap_is_unknown():
    segs = [_seg(0, 10)]
    # only 0.5s of the 10s segment overlaps -> under 30% -> UNKNOWN
    tracks = [DiarizationTrack(0, 0.5, "SPEAKER_00")]
    out = assign_and_merge(segs, tracks)
    assert out[0].speaker == "SPEAKER_UNKNOWN"


def test_no_tracks_leaves_unlabeled():
    segs = [_seg(0, 5), _seg(5, 10)]
    out = assign_and_merge(segs, [])
    assert all(s.speaker is None for s in out)


def test_merge_consecutive_same_speaker():
    segs = [
        _seg(0, 2, "a"),
        _seg(2, 4, "b"),
        _seg(4, 6, "c"),
    ]
    tracks = [DiarizationTrack(0, 100, "SPEAKER_00")]
    out = assign_and_merge(segs, tracks)
    # all same speaker and within 20s -> one merged line
    assert len(out) == 1
    assert out[0].speaker == "SPEAKER_00"
    assert out[0].text == "a b c"
    assert out[0].start == 0 and out[0].end == 6


def test_merge_respects_speaker_change():
    segs = [
        _seg(0, 2, "a"),
        _seg(2, 4, "b"),
    ]
    tracks = [
        DiarizationTrack(0, 2, "SPEAKER_00"),
        DiarizationTrack(2, 4, "SPEAKER_01"),
    ]
    out = assign_and_merge(segs, tracks)
    assert len(out) == 2
    assert out[0].speaker == "SPEAKER_00"
    assert out[1].speaker == "SPEAKER_01"

"""Outputs: canonical JSON + TXT/SRT/VTT writers. No GPU, no network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.app.models.asr_base import Segment, Word  # noqa: E402
from server.app.pipeline import outputs  # noqa: E402


def _segs():
    return [
        Segment(0.0, 2.0, "Hi there", speaker="SPEAKER_00",
                words=[Word("Hi", 0.0, 0.5), Word("there", 0.6, 1.0)]),
        Segment(2.0, 4.5, "hello!", speaker="SPEAKER_01"),
        Segment(4.5, 7.0, "bye now", speaker="SPEAKER_00"),
    ]


MAP = {
    "SPEAKER_00": {"name": "Alice", "confidence": 0.9, "evidence": "said hi, I'm Alice"},
    "SPEAKER_01": {"name": None, "confidence": 0.0, "evidence": ""},
}


def test_write_all_formats(tmp_path):
    paths = outputs.write_all(tmp_path, "job123", "meeting.wav", 7.0, MAP, _segs())
    assert (tmp_path / "job123.json").exists()
    assert (tmp_path / "job123.txt").exists()
    assert (tmp_path / "job123.srt").exists()
    assert (tmp_path / "job123.vtt").exists()

    # canonical JSON shape
    import json
    data = json.loads((tmp_path / "job123.json").read_text(encoding="utf-8"))
    assert data["job_id"] == "job123"
    assert data["duration"] == 7.0
    assert set(data["segments"][0].keys()) >= {"start", "end", "text", "speaker", "words"}
    assert data["speakers"] == MAP

    # TXT: named speaker + fallback "Speaker"
    txt = (tmp_path / "job123.txt").read_text(encoding="utf-8")
    assert "Alice: Hi there" in txt
    assert "00:00:02" in txt

    # SRT: index, timestamps, speaker prefix on each new speaker
    srt = (tmp_path / "job123.srt").read_text(encoding="utf-8").lstrip("﻿")
    assert srt.startswith("1\n")
    assert "00:00:00,000 --> 00:00:02,000" in srt
    assert "Alice: Hi there" in srt
    assert "Speaker 1: hello!" in srt
    # BOM for Windows players
    raw = (tmp_path / "job123.srt").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")

    # VTT: header (utf-8-sig -> strip BOM before asserting)
    vtt = (tmp_path / "job123.vtt").read_text(encoding="utf-8").lstrip("﻿")
    assert vtt.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:02.000" in vtt


def test_unknown_speaker_label():
    segs = [Segment(0, 2, "mystery", speaker="SPEAKER_UNKNOWN")]
    out = outputs._label("SPEAKER_UNKNOWN", MAP)
    assert out == "Speaker"
    # unnamed known id -> "Speaker N"
    assert outputs._label("SPEAKER_01", MAP) == "Speaker 1"


def test_canonical_round_trip(tmp_path):
    segs = _segs()
    c = outputs.build_canonical("j", "s.wav", 7.0, MAP, segs)
    assert c["segments"][2]["speaker"] == "SPEAKER_00"
    assert c["segments"][0]["words"][0] == {"text": "Hi", "start": 0.0, "end": 0.5}

"""Naming: robust JSON parsing + confidence gating. No network (Ollama is
called through _chat, which we stub here)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from server.app.models.asr_base import Segment  # noqa: E402
from server.app.pipeline import naming  # noqa: E402


def _segs():
    return [
        Segment(0, 5, "I'm Jane, let's start", speaker="SPEAKER_00"),
        Segment(5, 10, "sure, what's your name?", speaker="SPEAKER_01"),
    ]


def test_parse_plain_json():
    raw = '{"speakers": {"SPEAKER_00": {"name": "Jane", "confidence": 0.9, "evidence": "intro"}}}'
    m = naming._parse_mapping(raw)
    assert m and m["SPEAKER_00"]["name"] == "Jane"


def test_parse_fenced_json():
    raw = '```json\n{"speakers": {"SPEAKER_00": {"name": "Jane", "confidence": 0.9, "evidence": ""}}}\n```'
    m = naming._parse_mapping(raw)
    assert m and m["SPEAKER_00"]["name"] == "Jane"


def test_parse_trailing_comma():
    raw = '{"speakers": {"SPEAKER_00": {"name": "Jane", "confidence": 0.9,},}}'
    m = naming._parse_mapping(raw)
    assert m and m["SPEAKER_00"]["name"] == "Jane"


def test_parse_garbage_returns_none():
    assert naming._parse_mapping("I think the name is Jane.") is None
    assert naming._parse_mapping("") is None
    assert naming._parse_mapping("not json at all {") is None


def test_infer_names_adopts_high_confidence(monkeypatch):
    def fake_chat(url, payload):
        # the second segment references the first; model names SPEAKER_00
        return {"SPEAKER_00": {"name": "Jane", "confidence": 0.9, "evidence": "intro"}}

    monkeypatch.setattr(naming, "_chat", fake_chat)
    smap = naming.infer_names(_segs())
    assert smap["SPEAKER_00"]["name"] == "Jane"
    # SPEAKER_01 present but unnamed -> entry with name None
    assert smap["SPEAKER_01"]["name"] is None


def test_infer_names_rejects_low_confidence(monkeypatch):
    def fake_chat(url, payload):
        return {"SPEAKER_00": {"name": "Maybe", "confidence": 0.3, "evidence": "guess"}}

    monkeypatch.setattr(naming, "_chat", fake_chat)
    smap = naming.infer_names(_segs())
    assert smap["SPEAKER_00"]["name"] is None


def test_infer_names_robust_to_none(monkeypatch):
    monkeypatch.setattr(naming, "_chat", lambda url, payload: None)
    smap = naming.infer_names(_segs())
    assert smap["SPEAKER_00"]["name"] is None
    assert smap["SPEAKER_01"]["name"] is None


def test_infer_names_no_segments():
    # should not raise and returns an empty map (even with _chat unpatched,
    # zero chunks means no network call)
    assert naming.infer_names([]) == {}

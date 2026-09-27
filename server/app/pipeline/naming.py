"""Ollama-based speaker naming.

Reads the speaker-labeled dialogue in time-ordered chunks and asks the LLM to
assign real names where a speaker is actually named in what's said. The model
must emit strict JSON; we parse defensively (strip fences, repair trailing
commas, one retry, else discard the chunk).

VRAM choreography lives in the worker: it calls `manager.prepare_for_ollama()`
BEFORE building this pass, so Ollama (a 27B GGUF, ~13.7 GB) is never resident
at the same time as ASR/diarization.

A "confirmed-so-far" map is carried across chunks so a speaker keeps the same
identity and later chunks are cheap (they mostly reconfirm).
"""
from __future__ import annotations

import json
import logging
import re
from contextlib import contextmanager
from typing import Callable

import httpx

from .. import usage
from ..config import settings

log = logging.getLogger(__name__)

ProgressCB = Callable[[float, str], None]

_CONF_MIN = 0.6
_CHUNK_SEC = 900.0  # ~15 min per chunk
_OVERLAP_SEC = 60.0  # 1 line of overlap to keep context continuous

_SYSTEM = (
    "You are assigning real names to speakers in a transcript. You are given a "
    "segment of dialogue where each line is prefixed with an anonymous speaker "
    "id (SPEAKER_00, SPEAKER_01, ...). Infer a person's real name ONLY if it is "
    "explicitly spoken or unambiguously referenced (introductions, signatures, "
    "etc.). Do NOT invent names. Return ONLY JSON of the form: "
    '{"speakers": {"SPEAKER_00": {"name": "Jane Doe", "confidence": 0.9, '
    '"evidence": "she said I am Jane"}}, "notes": "optional"}. '
    "Use null for name when unknown. Only include speakers present in this "
    "segment."
)


def _strip_fences(t: str) -> str:
    t = t.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _parse_mapping(raw: str) -> dict | None:
    """robust parse -> {speaker_id: {name,confidence,evidence}} or None."""
    if raw is None:
        return None
    t = _strip_fences(raw)
    if not t:
        return None
    for candidate in (t, re.sub(r",\s*([}\]])", r"\1", t)):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and isinstance(obj.get("speakers"), dict):
                return obj["speakers"]
        except json.JSONDecodeError:
            continue
    return None


def _chunk_segments(segments, chunk_sec=_CHUNK_SEC, overlap_sec=_OVERLAP_SEC):
    """Yield lists of consecutive segments, each spanning <= chunk_sec.

    Consecutive chunks overlap by at most `overlap_sec` of trailing lines so
    the model keeps context across the boundary (names it already confirmed).
    """
    if not segments:
        return
    cur = [segments[0]]
    for s in segments[1:]:
        if s.start - cur[0].start > chunk_sec:
            yield cur
            # carry a little of the tail into the next chunk for continuity
            tail = [x for x in cur if x.start >= cur[-1].end - overlap_sec]
            cur = tail + [s]
        else:
            cur.append(s)
    yield cur


def _line(segs) -> str:
    out = []
    for s in segs:
        spk = s.speaker or "SPEAKER_UNKNOWN"
        out.append(f"[{spk}] {s.text}")
    return "\n".join(out)


def _format_confirmed(confirmed: dict) -> str:
    if not confirmed:
        return ""
    lines = ["Already-confirmed speaker names so far (reuse them, don't change):"]
    for sid, info in confirmed.items():
        nm = info.get("name")
        if nm:
            lines.append(f"  {sid} = {nm}")
    return "\n".join(lines) + "\n\n"


def infer_names(
    segments,
    progress_cb: ProgressCB | None = None,
    ollama_url: str | None = None,
    model: str | None = None,
) -> dict:
    """Return speaker_map {speaker_id: {name, confidence, evidence}}.

    Never raises for a bad LLM answer — a chunk that can't be parsed is simply
    discarded and those speakers stay "Speaker N".
    """
    s = settings()
    url = (ollama_url or s.ollama_url).rstrip("/")
    model = model or s.ollama_model

    # only speakers that actually appear are candidates
    present = [sp for sp in dict.fromkeys(x.speaker for x in segments) if sp]
    confirmed: dict = {}
    chunks = list(_chunk_segments(segments))
    n = max(1, len(chunks))

    for i, chunk in enumerate(chunks):
        prompt = _format_confirmed(confirmed) + _line(chunk)
        payload = {
            "model": model,
            "stream": False,
            "options": {"temperature": 0, "num_ctx": 16384},
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
        }
        mapping = _chat(url, payload) or {}
        for sid, info in mapping.items():
            if not isinstance(info, dict):
                continue
            name = info.get("name")
            conf = float(info.get("confidence", 0.0) or 0.0)
            evidence = info.get("evidence") or ""
            if name and conf >= _CONF_MIN and sid in present:
                # adopt unless we already hold a DIFFERENT confirmed name
                existing = confirmed.get(sid, {}).get("name")
                if existing and existing != name:
                    # contradiction: keep the first, note evidence
                    continue
                confirmed[sid] = {"name": name, "confidence": conf, "evidence": evidence}
        if progress_cb:
            progress_cb((i + 1) / n, f"naming chunk {i+1}/{n}")

    # normalize: every present speaker gets an entry (name may be None)
    speaker_map = {}
    for sid in present:
        info = confirmed.get(sid)
        speaker_map[sid] = {
            "name": (info or {}).get("name"),
            "confidence": (info or {}).get("confidence", 0.0),
            "evidence": (info or {}).get("evidence", ""),
        }
    return speaker_map


@contextmanager
def llm_session():
    """Run Ollama-backed work, then unload resident models on exit.

    Wrap any operation that talks to Ollama (the naming pass, a summary, a
    chat answer). `unload_all()` runs in the `finally` — success or error —
    and any failure to unload is logged, never raised, so a flaky or missing
    Ollama can never break the operation that just finished. The caller has
    already called `manager.prepare_for_ollama()` before entering, keeping
    the "prepare before, unload after" symmetry.
    """
    try:
        yield
    finally:
        try:
            unload_all()
        except Exception:  # noqa: BLE001
            log.warning("failed to unload resident Ollama models", exc_info=True)


def unload_all(ollama_url: str | None = None) -> None:
    """Ask Ollama to unload every model currently resident in VRAM.

    Called when a job starts (so a model left over from a previous run frees
    VRAM before ASR loads) and after every Ollama-backed operation finishes,
    via `llm_session()`. Never raises — a missing/unreachable Ollama just
    means there's nothing loaded by us.
    """
    s = settings()
    url = (ollama_url or s.ollama_url).rstrip("/")
    try:
        resp = httpx.get(url + "/api/ps", timeout=10.0)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
    except (httpx.HTTPError, ValueError, KeyError):
        return
    for name in models:
        try:
            httpx.post(
                url + "/api/generate",
                json={"model": name, "keep_alive": 0},
                timeout=60.0,
            ).raise_for_status()
        except httpx.HTTPError:
            pass


def _chat(url: str, payload: dict) -> dict | None:
    """POST /api/chat, return parsed speaker mapping or None (robust)."""
    try:
        resp = httpx.post(
            url + "/api/chat", json=payload, timeout=httpx.Timeout(600.0, connect=10.0)
        )
        resp.raise_for_status()
        data = resp.json()
        usage.add(int(data.get("prompt_eval_count", 0)), int(data.get("eval_count", 0)))
        content = data.get("message", {}).get("content", "")
    except (httpx.HTTPError, ValueError, json.JSONDecodeError):
        # retry once on any transport/parse hiccup
        try:
            resp = httpx.post(
                url + "/api/chat", json=payload, timeout=httpx.Timeout(600.0, connect=10.0)
            )
            resp.raise_for_status()
            data = resp.json()
            usage.add(int(data.get("prompt_eval_count", 0)), int(data.get("eval_count", 0)))
            content = data.get("message", {}).get("content", "")
        except Exception:  # noqa: BLE001
            return None
    return _parse_mapping(content)

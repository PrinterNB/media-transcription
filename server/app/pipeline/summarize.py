"""Template-based summaries + Q&A over a finished transcript.

Runs entirely against Ollama (same endpoint/pattern as naming.py): no local
models are involved, but the caller must have already called
`manager.prepare_for_ollama()` so ASR/diarization are out of VRAM first.

Transcripts longer than a safe prompt budget are handled map-reduce style:
they are split at segment boundaries into ~40k-char sections, each section is
digested, and the final template prompt runs over the digests (for chat, over
the digests plus the most recent part of the transcript verbatim).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

import httpx

from .. import usage
from ..config import settings
from .outputs import _label

ProgressCB = Callable[[float, str], None]

# Character budgets. num_ctx is 16384 tokens (~4 chars/token), so a ~60k-char
# transcript leaves room for the system prompt plus a long answer.
WHOLE_BUDGET = 60_000  # below this, the transcript is sent whole
CHUNK_BUDGET = 40_000  # map-reduce: max chars per section digest
TAIL_BUDGET = 20_000  # chat context: keep this much of the end verbatim


@dataclass(frozen=True)
class Template:
    id: str
    label: str
    system: str


_COMMON = (
    "You will be given the transcript of a conversation, interview, or meeting. "
    "Each line is prefixed with the speaker's name when it is known from the "
    "transcript, or with a label like 'Speaker 2' when the person was never "
    "identified. Be strictly faithful to the transcript: report only what was "
    "actually said. Do not add outside knowledge, do not invent people, facts, "
    "numbers, dates, or decisions, and do not speculate beyond what is on the "
    "record. Refer to participants by name wherever the transcript gives one, "
    "otherwise by their speaker label, and attribute claims and opinions to "
    "the person who made them. Where the transcript is ambiguous or the "
    "speakers disagree, say so briefly rather than picking a side. Output plain "
    "text; light Markdown (headings and bullets) is fine where the requested "
    "format calls for it."
)


def _tpl(body: str) -> str:
    return _COMMON + " " + body


TEMPLATES: list[Template] = [
    Template(
        "tldr",
        "TL;DR",
        _tpl(
            "Produce a TL;DR of the transcript in ONE OR TWO sentences total. "
            "The first sentence must state what this conversation or meeting "
            "was fundamentally about; use a second sentence only to state its "
            "main outcome, decision, or point of contention. No headings, no "
            "bullets, no preamble — just the sentence(s)."
        ),
    ),
    Template(
        "summary",
        "Concise Summary",
        _tpl(
            "Write a concise summary of the entire conversation or meeting: "
            "one to three short paragraphs, roughly 120 to 250 words, prose "
            "only (no headings or bullets). Cover, in order: what the "
            "discussion was about; the main points that were raised, "
            "attributing significant claims to the person who made them where "
            "names are known; and how things stood at the end — decisions, "
            "agreements, or open ends. Start directly; no preamble such as "
            "'This conversation was about'."
        ),
    ),
    Template(
        "detailed",
        "Detailed Summary",
        _tpl(
            "Write a detailed, multi-paragraph summary organized with section "
            "headings (Markdown '## ' lines) that you choose to match the "
            "actual topics of the conversation — not generic ones like "
            "'Introduction' or 'Discussion'. Cover every substantive topic in "
            "the order it came up. Preserve important specifics: names, "
            "numbers, dates, deadlines, and product or feature names. "
            "Attribute significant claims and positions to the person who made "
            "them by name where known. Note disagreements and how each was "
            "resolved or left open. End with a short 'Outcome' heading section "
            "recapping decisions and next steps if any were stated. Aim for "
            "as much depth as the transcript warrants (roughly 400 to 900 "
            "words for a normal meeting, more for a long one)."
        ),
    ),
    Template(
        "meeting_notes",
        "Meeting Notes",
        _tpl(
            "Format the output as meeting notes with exactly these sections, "
            "in this order, each as a Markdown heading:\n"
            "1. 'Overview' — one short paragraph (2 to 4 sentences) describing "
            "what was discussed and the outcome.\n"
            "2. 'Key Points' — bulleted list of the significant points raised, "
            "each attributed to who raised it when a name is known.\n"
            "3. 'Action Items' — bulleted list of every commitment or task. "
            "Each bullet states the action, its owner (the name of who "
            "committed, otherwise 'unassigned'), and the due date or deadline "
            "when one was mentioned (otherwise 'not stated'). If there are "
            "none, write a single bullet: 'None stated.'\n"
            "4. 'Decisions Made' — bulleted list; each bullet states the "
            "decision and the rationale for it (the stated reason, or the "
            "reasoning given in the discussion). If there are none, write "
            "'None stated.'\n"
            "5. 'Follow-up Questions / Unresolved Items' — bulleted list of "
            "open questions, deferred items, and disagreements that were not "
            "resolved. If there are none, write 'None.'\n"
            "Be faithful to the transcript and note who said what where names "
            "are known; keep it organized and skimmable."
        ),
    ),
    Template(
        "action_items",
        "Action Items",
        _tpl(
            "Extract every concrete action item from the transcript: anything "
            "someone said they would do, a task that was assigned, a "
            "commitment, or a deadline. Output a single bulleted list, in the "
            "order the items appeared, one item per bullet, each formatted as: "
            "the action — Owner: <name when the transcript makes it clear who "
            "is responsible, otherwise 'unassigned'> — Due: <the date or "
            "deadline when mentioned, otherwise 'not stated'>. Include only "
            "actions; do not include background, discussion, or decisions "
            "that are not also actions. If the transcript contains no action "
            "items, output exactly: None stated."
        ),
    ),
    Template(
        "discussion",
        "Key Discussion Points",
        _tpl(
            "Identify the key discussion points: the topics that were actually "
            "debated or examined in depth, not merely mentioned. For each one, "
            "in the order it came up, write a Markdown heading naming the "
            "topic, then: (a) one or two sentences on what was discussed; "
            "(b) the differing views, each attributed to the person who held "
            "it (by name when known); and (c) how it was resolved — a "
            "decision, an agreement, a deferral, or left unresolved — "
            "quoting or closely paraphrasing any explicit statement of the "
            "outcome. Close with a short note on where agreement was reached "
            "and where it was not, if the transcript is substantial enough to "
            "warrant one."
        ),
    ),
    Template(
        "decisions",
        "Decisions Made",
        _tpl(
            "List every decision the transcript records as made, chronologically, "
            "one bullet per decision. Each bullet states the decision itself up "
            "front, then its rationale: the explicit reason when one was "
            "given, otherwise the reasoning that led to it as it was argued in "
            "the transcript. Attribute each decision to the person who made it "
            "when that is clear. Include any conditions, exceptions, or "
            "follow-ups attached to a decision. If something is only under "
            "discussion or deferred rather than decided, say so explicitly in "
            "that bullet. If the transcript records no decisions, output "
            "exactly: None stated."
        ),
    ),
]


def list_templates() -> list[dict]:
    """Public registry: [{'id', 'label'}, ...] (order shown in the UI)."""
    return [{"id": t.id, "label": t.label} for t in TEMPLATES]


def get_template(template_id: str) -> Template | None:
    return next((t for t in TEMPLATES if t.id == template_id), None)


# ---------- transcript rendering ----------
def _line(seg, speaker_map: dict) -> str | None:
    """One transcript line, 'Speaker: text', mirroring the TXT writer labels."""
    if isinstance(seg, dict):
        text, speaker = seg.get("text"), seg.get("speaker")
    else:
        text, speaker = seg.text, seg.speaker
    text = (text or "").strip()
    if not text:
        return None
    return f"{_label(speaker, speaker_map)}: {text}"


def build_transcript_text(segments, speaker_map: dict | None = None) -> str:
    """Render segments as 'SPEAKER: text' lines (same labels as outputs.py)."""
    speaker_map = speaker_map or {}
    lines = [_line(s, speaker_map) for s in (segments or [])]
    return "\n".join(l for l in lines if l is not None)


def _chunk_segments(segments, speaker_map: dict, budget: int) -> list[list]:
    """Group consecutive segments so each group's rendered text fits in budget."""
    chunks: list[list] = []
    cur: list = []
    cur_len = 0
    for seg in segments:
        line = _line(seg, speaker_map)
        if line is None:
            continue
        if cur and cur_len + len(line) + 1 > budget:
            chunks.append(cur)
            cur, cur_len = [], 0
        cur.append(seg)
        cur_len += len(line) + 1
    if cur:
        chunks.append(cur)
    return chunks


_DIGEST_SYSTEM = (
    "You are digesting one section of a longer conversation or meeting "
    "transcript. Each line is prefixed with the speaker's name when known, "
    "otherwise a label like 'Speaker 2'. Produce a faithful, detailed digest "
    "of ONLY this section that preserves everything a summary of the full "
    "transcript will need: every topic and how it developed; decisions, "
    "commitments, and action items (with owner and due date when stated); "
    "disagreements and who held which view; and important specifics such as "
    "names, numbers, dates, and deadlines. Use light Markdown with a short "
    "bold topic line per sub-topic. Be thorough rather than brief, but do not "
    "add anything that is not in this section."
)

_MAP_NOTE = (
    "(The full transcript was too long to include in one prompt. Below are "
    "faithful, in-order digests of its sections. Summarize the conversation as "
    "a whole, across all sections.)\n\n"
)

_CHAT_NOTE = (
    "(The transcript was too long to include in full: its earlier sections are "
    "summarized as a faithful digest below, followed by its most recent part "
    "verbatim.)\n"
)

_CHAT_SYSTEM = (
    "You are answering questions about the following transcript of a "
    "conversation or meeting. Each transcript line is prefixed with the "
    "speaker's name when known, or with a label like 'Speaker 2' when the "
    "person was never identified. Answer ONLY from the transcript: do not use "
    "outside knowledge or add facts that are not in it. Cite speakers by name "
    "when known, and ground your answers in who said what. If the answer is "
    "not in the transcript, say so plainly instead of guessing. Be concise "
    "and direct. If the transcript was too long to include in full, its "
    "earlier sections appear as a digest and its most recent part verbatim."
)


def _section_digests(
    segments, speaker_map: dict, url: str, model: str, progress_cb: ProgressCB | None = None
) -> list[str]:
    """Map phase: digest each section of an oversized transcript."""
    chunks = _chunk_segments(segments, speaker_map, CHUNK_BUDGET)
    n = max(1, len(chunks))
    out: list[str] = []
    for i, chunk in enumerate(chunks):
        text = build_transcript_text(chunk, speaker_map)
        if progress_cb:
            progress_cb(i / n, f"digest section {i + 1}/{n}")
        r = _chat(
            url,
            model,
            [
                {"role": "system", "content": _DIGEST_SYSTEM},
                {"role": "user", "content": text},
            ],
        )
        out.append((r or "").strip())
    return out


def run_template(
    job: dict,
    template_id: str,
    model: str | None = None,
    progress_cb: ProgressCB | None = None,
) -> str:
    """Run one summary template over a job's transcript; return the text.

    `job` is a full job dict (needs 'segments', 'speaker_map', 'options');
    segments may be dicts (from the DB) or Segment dataclasses (in the
    worker). Raises ValueError for an unknown template or empty transcript;
    returns '' when Ollama is unreachable or answers with nothing.
    """
    tpl = get_template(template_id)
    if tpl is None:
        raise ValueError(f"unknown summary template: {template_id!r}")
    segments = job.get("segments") or []
    speaker_map = job.get("speaker_map") or {}
    text = build_transcript_text(segments, speaker_map)
    if not text.strip():
        raise ValueError("no transcript text to summarize")

    s = settings()
    model = model or (job.get("options", {}).get("ollama_model") or s.ollama_model)
    url = s.ollama_url.rstrip("/")

    def _report(frac: float, msg: str = "") -> None:
        if progress_cb:
            progress_cb(min(1.0, max(0.0, frac)), msg)

    if len(text) <= WHOLE_BUDGET:
        _report(0.1, "Summarizing…")
        result = _chat(
            url,
            model,
            [
                {"role": "system", "content": tpl.system},
                {"role": "user", "content": text},
            ],
        )
    else:
        # map-reduce: digest each section (0 -> 0.85), then combine (-> 1.0)
        def _map_progress(frac: float, msg: str = "") -> None:
            _report(0.85 * frac, msg)

        digests = _section_digests(segments, speaker_map, url, model, _map_progress)
        _report(0.9, "Combining sections…")
        body = _MAP_NOTE + "\n\n".join(d for d in digests if d.strip())
        result = _chat(
            url,
            model,
            [
                {"role": "system", "content": tpl.system},
                {"role": "user", "content": body},
            ],
        )
    _report(1.0, "done")
    return (result or "").strip()


def build_chat_context(segments, speaker_map: dict, url: str, model: str) -> str:
    """Transcript context for a chat question, with the same length strategy:
    the whole text when it fits, else section digests plus the most recent
    ~20k chars verbatim (so recent content is directly quotable)."""
    text = build_transcript_text(segments, speaker_map)
    if not text.strip() or len(text) <= WHOLE_BUDGET:
        return text
    digests = _section_digests(segments, speaker_map, url, model)
    tail: list[str] = []
    n = 0
    for line in reversed(text.splitlines()):
        tail.append(line)
        n += len(line) + 1
        if n >= TAIL_BUDGET:
            break
    tail_text = "\n".join(reversed(tail))
    head = _CHAT_NOTE + "\n\n".join(d for d in digests if d.strip())
    return head.strip() + "\n\n" + tail_text


def answer(job: dict, message: str, history: list, model: str | None = None) -> str:
    """Answer one question about a finished job's transcript.

    `history` is a list of {'role': 'user'|'assistant', 'content': str}
    (oldest first); returns the reply text ('' when Ollama has no answer).
    """
    s = settings()
    model = model or (job.get("options", {}).get("ollama_model") or s.ollama_model)
    url = s.ollama_url.rstrip("/")
    context = build_chat_context(job.get("segments") or [], job.get("speaker_map") or {}, url, model)
    system = _CHAT_SYSTEM + "\n\nTRANSCRIPT:\n" + context
    messages = [{"role": "system", "content": system}]
    messages += [
        {"role": m["role"], "content": m["content"]}
        for m in history
        if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)
    ]
    messages.append({"role": "user", "content": message})
    return (_chat(url, model, messages) or "").strip()


def _chat(url: str, model: str, messages: list[dict]) -> str | None:
    """POST /api/chat, return the assistant's text content or None (robust).

    Same pattern as naming._chat (one retry, 600 s timeout, temperature 0,
    num_ctx 16384) but returns the raw text — naming's copy parses JSON.
    """
    payload = {
        "model": model,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": 16384},
        "messages": messages,
    }
    for attempt in (1, 2):
        try:
            resp = httpx.post(
                url + "/api/chat", json=payload, timeout=httpx.Timeout(600.0, connect=10.0)
            )
            resp.raise_for_status()
            data = resp.json()
            usage.add(int(data.get("prompt_eval_count", 0)), int(data.get("eval_count", 0)))
            return data.get("message", {}).get("content", "")
        except (httpx.HTTPError, ValueError, json.JSONDecodeError):
            if attempt == 2:
                return None
    return None

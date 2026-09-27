"""Per-thread accumulator for Ollama token usage.

Ollama calls happen on the worker thread (naming, auto-summary) and on
FastAPI's threadpool (the /summarize and /chat routes), so the counter is
thread-local: a `_chat` response adds its counts, and the caller that knows
the job id flushes them into the job row.
"""
from __future__ import annotations

import threading

_tl = threading.local()


def add(prompt: int, completion: int) -> None:
    acc = getattr(_tl, "acc", (0, 0))
    _tl.acc = (acc[0] + int(prompt), acc[1] + int(completion))


def take() -> tuple[int, int]:
    """Return this thread's accumulated (prompt, completion) and reset it."""
    acc = getattr(_tl, "acc", (0, 0))
    _tl.acc = (0, 0)
    return acc


def flush(job_id: str) -> None:
    """Write this thread's accumulated usage to the job row, if any."""
    prompt, completion = take()
    if prompt or completion:
        from .db import get_db  # lazy: avoid import cycles / test isolation

        get_db().add_usage(job_id, prompt, completion)

"""Server-Sent Events job stream (polling model).

The pipeline worker runs in a background (sync) thread and updates the sqlite
row — the single source of truth. SSE clients don't need a push bus: each open
stream just polls the row on a short interval and emits when the cheap status
fields change. This is thread-safe by construction (no cross-thread asyncio
queues), cheap (one indexed sqlite read per client per ~0.4s), and reconnects
for free via EventSource.

A client reconnecting mid-job sees the live row immediately, so reconnect ==
re-GET.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Callable

_INTERVAL = 0.4


def _fingerprint(snap: dict) -> tuple:
    """Cheap fields that indicate a visible change (excludes big segments /
    speaker_map blobs, which only appear on the terminal update that also
    flips status)."""
    return (
        snap.get("status"),
        snap.get("stage"),
        snap.get("progress"),
        snap.get("message"),
        snap.get("error"),
        snap.get("detected_language"),
    )


async def stream_job(
    get_snapshot: Callable[[], dict],
    terminal: tuple = ("done", "error", "cancelled"),
) -> AsyncIterator[tuple[str, str]]:
    """Yield ('job_update', json) tuples until the job reaches a terminal state.

    `get_snapshot` is a sync callable returning the full job dict (reads the
    DB under its lock — fast, so it's fine on the loop).
    """
    last: tuple | None = None
    while True:
        snap = get_snapshot()
        fp = _fingerprint(snap)
        if fp != last:
            yield "job_update", json.dumps(snap, default=str)
            last = fp
        if snap.get("status") in terminal:
            # emit the final full snapshot (with segments/speaker_map) once more
            yield "job_update", json.dumps(snap, default=str)
            return
        await asyncio.sleep(_INTERVAL)

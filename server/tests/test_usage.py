"""Token usage: db.add_usage increments, and a stubbed Ollama response's
counts flow through usage.add/flush into the job row."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_add_usage_increments(db_reset):
    from server.app.db import get_db

    job = get_db().create("a.wav", 12, {}, owner="admin")
    get_db().add_usage(job["id"], 7, 9)
    get_db().add_usage(job["id"], 3, 1)
    row = get_db().get(job["id"])
    assert row["prompt_tokens"] == 10
    assert row["completion_tokens"] == 10


def test_stubbed_ollama_counts_flow_to_job_row(db_reset, monkeypatch):
    from server.app import usage
    from server.app.db import get_db
    from server.app.pipeline import naming

    job = get_db().create("a.wav", 12, {}, owner="admin")

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "message": {"content": '{"speakers": {}}'},
                "prompt_eval_count": 123,
                "eval_count": 45,
            }

    monkeypatch.setattr(
        naming.httpx, "post", lambda url, json=None, timeout=None: _Resp()
    )
    naming._chat("http://ollama.test", {"model": "x"})
    usage.flush(job["id"])

    row = get_db().get(job["id"])
    assert row["prompt_tokens"] == 123
    assert row["completion_tokens"] == 45


def test_flush_without_usage_is_noop(db_reset):
    from server.app import usage
    from server.app.db import get_db

    job = get_db().create("a.wav", 12, {}, owner="admin")
    usage.flush(job["id"])  # nothing accumulated
    row = get_db().get(job["id"])
    assert row["prompt_tokens"] == 0
    assert row["completion_tokens"] == 0

"""POST /api/jobs: creating a job with a summary template pre-selected.

No worker thread runs in these tests: the route's get_worker is stubbed and
the TestClient is used outside its context manager (no lifespan), so the job
row is exactly what the route stored.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest


class _Worker:
    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit(self, job_id: str) -> None:
        self.submitted.append(job_id)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from server.app import db as db_mod
    from server.app.config import settings as _settings
    from server.app.routes import uploads as uploads_route

    # isolate the job store: fresh DATA_DIR + fresh db singleton
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    _settings.cache_clear()
    db_mod._jobs = None

    # swallow the submit so no real worker thread ever picks the job up
    monkeypatch.setattr(uploads_route, "get_worker", lambda: _Worker())

    from server.app.main import app

    yield TestClient(app)

    db_mod._jobs = None
    _settings.cache_clear()


def _upload(client, template: str | None = None) -> int:
    data = {}
    if template is not None:
        data["summary_template"] = template
    r = client.post(
        "/api/jobs",
        files={"file": ("meeting.mkv", b"RIFF-fake-audio", "video/x-matroska")},
        data={"asr": "canary", "extracted": "false", **data},
    )
    return r.status_code


def test_create_job_queues_selected_summary_template(client):
    r = client.post(
        "/api/jobs",
        files={"file": ("meeting.mkv", b"RIFF-fake-audio", "video/x-matroska")},
        data={"asr": "canary", "extracted": "false", "summary_template": "meeting_notes"},
    )
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["pending_summary"] == "meeting_notes"
    assert job["options"]["summary_template"] == "meeting_notes"
    # and it's in the row the worker would read
    from server.app.db import get_db

    assert get_db().get(job["id"])["pending_summary"] == "meeting_notes"


def test_create_job_without_template_leaves_pending_null(client):
    status = _upload(client)
    assert status == 202
    r = client.get("/api/jobs")
    assert r.status_code == 200
    jobs = r.json()
    assert len(jobs) == 1
    assert jobs[0]["pending_summary"] is None
    assert jobs[0]["options"]["summary_template"] is None


def test_create_job_blank_template_leaves_pending_null(client):
    status = _upload(client, template="")
    assert status == 202
    r = client.get("/api/jobs")
    assert r.json()[0]["pending_summary"] is None


def test_create_job_invalid_template_rejected(client):
    status = _upload(client, template="no_such_template")
    assert status == 400
    assert client.get("/api/jobs").json() == []

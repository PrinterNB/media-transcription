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

    from server.app import auth as auth_mod
    from server.app import db as db_mod
    from server.app.config import settings as _settings
    from server.app.routes import uploads as uploads_route

    # isolate the job store: fresh DATA_DIR + fresh db singleton
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    # Pin the seeded admin so the real .env (a user's live account) can't
    # change who/what these tests log in as.
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("REQUIRE_APPROVAL", "false")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    _settings.cache_clear()
    db_mod._jobs = None

    # swallow the submit so no real worker thread ever picks the job up
    monkeypatch.setattr(uploads_route, "get_worker", lambda: _Worker())

    auth_mod.bootstrap()

    from server.app.main import app

    client = TestClient(app)
    r = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin"}
    )
    assert r.status_code == 200, r.text  # seeded by bootstrap, password from env

    yield client

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


def test_chat_unloads_ollama_after_answering(client, monkeypatch):
    """POST /{id}/chat prepares for Ollama, answers, then unloads resident
    models (the `llm_session` guard) — and still unloads when the answer
    fails."""
    from server.app.db import get_db
    from server.app.pipeline import naming
    from server.app.pipeline import summarize
    from server.app.routes import jobs as jobs_route

    # seed a finished job with a one-line transcript
    job = get_db().create("a.wav", 12, {})
    get_db().update(
        job["id"], status="done", stage="done", progress=100,
        speaker_map={},
        segments=[{"start": 0, "end": 2, "text": "hi", "speaker": "SPEAKER_00"}],
        finished=True,
    )

    prepared = []

    class _M:
        def prepare_for_ollama(self):
            prepared.append(1)

    monkeypatch.setattr(jobs_route, "get_manager", lambda: _M())
    monkeypatch.setattr(summarize, "_chat", lambda url, model, messages: "sure, me")
    unloads = []
    monkeypatch.setattr(naming, "unload_all", lambda url=None: unloads.append(url))

    r = client.post(f"/api/jobs/{job['id']}/chat", json={"message": "who spoke?"})
    assert r.status_code == 200, r.text
    assert r.json()["reply"] == "sure, me"
    assert prepared == [1]  # ASR/diarizer freed BEFORE Ollama
    assert unloads == [None]  # and resident models freed AFTER


def test_jobs_require_auth(client):
    from fastapi.testclient import TestClient

    from server.app.main import app

    assert TestClient(app).get("/api/jobs").status_code == 401


def test_per_user_isolation(client, monkeypatch):
    """Two accounts each create a job; each sees only their own, the other's
    id is a 404 (not 403 — no leaking ids), download of it 404s too."""
    from fastapi.testclient import TestClient

    from server.app.main import app
    from server.app.routes import uploads as uploads_route

    monkeypatch.setattr(uploads_route, "get_worker", lambda: _Worker())

    def upload(c) -> str:
        r = c.post(
            "/api/jobs",
            files={"file": ("m.mkv", b"RIFF-fake-audio", "video/x-matroska")},
            data={"asr": "canary", "extracted": "false"},
        )
        assert r.status_code == 202, r.text
        return r.json()["id"]

    other = TestClient(app)  # fresh browser, no cookies
    r = other.post(
        "/api/auth/signup", json={"username": "alice", "password": "password123"}
    )
    assert r.status_code == 201, r.text

    admin_job = upload(client)  # fixture client is logged in as admin
    alice_job = upload(other)

    assert [j["id"] for j in client.get("/api/jobs").json()] == [admin_job]
    assert [j["id"] for j in other.get("/api/jobs").json()] == [alice_job]

    # admin sees everything; alice sees neither admin's job nor it leaking
    assert client.get(f"/api/jobs/{alice_job}").status_code == 200
    assert other.get(f"/api/jobs/{admin_job}").status_code == 404
    assert (
        other.get(f"/api/jobs/{admin_job}/download").status_code == 404
    )


def test_delete_job_removes_row_and_files(client):
    from server.app.config import settings
    from server.app.db import get_db

    s = settings()
    job = get_db().create("a.wav", 12, {}, owner="admin")
    job_id = job["id"]
    get_db().update(job_id, status="done", stage="done", progress=100, finished=True)
    (s.uploads_dir / job_id).mkdir(parents=True)
    (s.uploads_dir / job_id / "a.wav").write_bytes(b"x")
    (s.outputs_dir / f"{job_id}.txt").write_text("t")

    r = client.delete(f"/api/jobs/{job_id}")
    assert r.status_code == 200, r.text
    assert get_db().get(job_id) is None
    assert not (s.uploads_dir / job_id).exists()
    assert not (s.outputs_dir / f"{job_id}.txt").exists()


def test_delete_job_not_own_is_404(client):
    from fastapi.testclient import TestClient

    from server.app.db import get_db
    from server.app.main import app

    other = TestClient(app)
    r = other.post(
        "/api/auth/signup", json={"username": "dave", "password": "password123"}
    )
    assert r.status_code == 201, r.text

    job = get_db().create("a.wav", 12, {}, owner="alice")  # alice's, not dave's
    r = other.delete(f"/api/jobs/{job['id']}")
    assert r.status_code == 404
    # still there
    assert get_db().get(job["id"]) is not None


def test_delete_running_job_409(client):
    from server.app.db import get_db

    job = get_db().create("a.wav", 12, {}, owner="admin")  # queued, not terminal
    r = client.delete(f"/api/jobs/{job['id']}")
    assert r.status_code == 409


def test_delete_my_jobs(client):
    from server.app.db import get_db

    db = get_db()
    j1 = db.create("a.wav", 12, {}, owner="admin")
    j2 = db.create("b.wav", 13, {}, owner="admin")
    db.update(j1["id"], status="done", finished=True)

    r = client.delete("/api/jobs/mine")
    assert r.status_code == 409  # j2 still queued

    db.update(j2["id"], status="done", finished=True)
    r = client.delete("/api/jobs/mine")
    assert r.status_code == 200, r.text
    assert r.json()["deleted_jobs"] == 2
    assert client.get("/api/jobs").json() == []


def test_nuclear_delete_requires_admin(client):
    from fastapi.testclient import TestClient

    from server.app.main import app

    other = TestClient(app)
    r = other.post(
        "/api/auth/signup", json={"username": "erin", "password": "password123"}
    )
    assert r.status_code == 201, r.text
    assert other.delete("/api/jobs").status_code == 403


def test_chat_unloads_even_when_ollama_fails(client, monkeypatch):
    from server.app.db import get_db
    from server.app.pipeline import naming
    from server.app.pipeline import summarize
    from server.app.routes import jobs as jobs_route

    job = get_db().create("a.wav", 12, {})
    get_db().update(
        job["id"], status="done", stage="done", progress=100,
        speaker_map={},
        segments=[{"start": 0, "end": 2, "text": "hi", "speaker": "SPEAKER_00"}],
        finished=True,
    )
    class _M:
        def prepare_for_ollama(self):
            pass

    monkeypatch.setattr(jobs_route, "get_manager", lambda: _M())
    monkeypatch.setattr(summarize, "_chat", lambda url, model, messages: None)
    unloads = []
    monkeypatch.setattr(naming, "unload_all", lambda url=None: unloads.append(url))

    r = client.post(f"/api/jobs/{job['id']}/chat", json={"message": "who spoke?"})
    assert r.status_code == 502, r.text  # no output, but...
    assert unloads == [None]  # ...the resident model was still unloaded

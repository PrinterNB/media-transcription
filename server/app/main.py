"""FastAPI app factory + entrypoint.

One uvicorn process serves the API and the built web frontend (web/dist) on
0.0.0.0:8000 so LAN devices can reach it. The job worker is a single daemon
thread started at lifespan; it's the only thing that touches the GPU models,
so the VRAM rule holds by construction.
"""
from __future__ import annotations

import socket
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .pipeline.worker import get_worker
from .routes import downloads, jobs, uploads


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker = get_worker()
    worker.start()
    s = settings()
    ip = _lan_ip()
    print("=" * 62)
    print(" media-transcription is running")
    print(f"   this machine : http://127.0.0.1:{s.port}")
    print(f"   on the LAN   : http://{ip}:{s.port}")
    print("=" * 62)
    yield
    # worker is a daemon; nothing to stop explicitly


def create_app() -> FastAPI:
    app = FastAPI(title="media-transcription", lifespan=lifespan)

    # The web UI calls /api from the same origin in prod, but during dev the
    # Vite server is a different origin — allow all (LAN app, no secrets here).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(uploads.router)
    app.include_router(jobs.router)
    app.include_router(downloads.router)

    # Serve the built frontend if it exists (web/dist). Mounted last so /api
    # wins; index.html is served at /.
    dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="web")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    s = settings()
    uvicorn.run("server.app.main:app", host=s.host, port=s.port, reload=False)

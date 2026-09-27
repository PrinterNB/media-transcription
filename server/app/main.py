"""FastAPI app factory + entrypoint.

One uvicorn process serves the API and the built web frontend (web/dist) on
0.0.0.0:8000 so LAN devices can reach it. The job worker is a single daemon
thread started at lifespan; it's the only thing that touches the GPU models,
so the VRAM rule holds by construction.
"""
from __future__ import annotations

import socket
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import qrcode
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import auth
from .config import settings
from .pipeline import naming
from .pipeline.worker import get_worker
from .routes import admin, auth as auth_routes, downloads, jobs, uploads


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


def _print_lan_qr(url: str) -> None:
    # QR of the LAN URL so a phone can be scanned into the app. TTY-only and
    # best-effort: piped stdout (tests, CI, logs) skips it, and a terminal
    # that chokes on the block glyphs must never block startup. Plain
    # characters (no ANSI codes) so it renders in any console font/theme.
    try:
        if not sys.stdout.isatty():
            return
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(url)
        print("   scan this from your phone to open the app:")
        qr.print_ascii()
    except Exception:  # noqa: BLE001  (banner is cosmetic; startup must not fail)
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed admin + settings + backfill job owners BEFORE the worker starts,
    # so `_resume_stale` only ever sees rows that have an owner.
    auth.bootstrap()
    worker = get_worker()
    worker.start()
    s = settings()
    ip = _lan_ip()
    lan_url = f"http://{ip}:{s.port}"
    print("=" * 62)
    print(" media-transcription is running")
    print(f"   this machine : http://127.0.0.1:{s.port}")
    print(f"   on the LAN   : {lan_url}")
    _print_lan_qr(lan_url)
    print("=" * 62)
    yield
    # worker is a daemon; nothing to stop explicitly.
    # Free any Ollama models still resident in VRAM — best-effort in a daemon
    # thread, so a slow or dead Ollama can neither hang shutdown nor raise.
    threading.Thread(
        target=_unload_ollama_best_effort,
        name="ollama-shutdown-unload",
        daemon=True,
    ).start()


def _unload_ollama_best_effort() -> None:
    try:
        naming.unload_all()
    except Exception:  # noqa: BLE001  (shutdown must never fail)
        pass


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

    app.include_router(auth_routes.router)
    app.include_router(admin.router)
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

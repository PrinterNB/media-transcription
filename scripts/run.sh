#!/bin/sh
# scripts/run.sh -- production launcher for media-transcription (macOS).
#
#   - creates the .venv with `uv sync` on first run, and keeps it in sync with
#     uv.lock afterwards (a fast no-op once it is already current)
#   - creates .env from .env.example on first run (chmod 600: it holds HF_TOKEN)
#   - installs web/node_modules if this is a fresh checkout
#   - builds web/dist if it is missing or older than anything under web/src
#   - launches uvicorn (no reload) serving API + web UI on 0.0.0.0:8000
#     (server/app/main.py prints the LAN IP + a QR code at boot)
#
# There is nothing for this script to put on PATH for the inference stack: the
# torch build here picks MPS and falls back to CPU inside Python, so the shell
# carries no accelerator search path, no console-encoding switch and no
# package-installation workaround -- the filesystem and the interpreter default
# to the right thing on this platform.
#
# Run from the project root:  ./scripts/run.sh
# The script finds the project root from its own location, so an absolute path
# to it works from anywhere; it changes directory only inside this process.

# -u catches a mistyped/renamed variable as a hard error instead of an empty
# string. Deliberately NOT -e: the uv sync below is expected to fail now and
# again, and the script inspects that first exit code on purpose.
set -u

SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd -P)
ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd -P)
VENV_PY="$ROOT/.venv/bin/python"
VENV_DIR="$ROOT/.venv"

if ! cd "$ROOT"; then
    printf 'error: cannot enter project root %s\n' "$ROOT" >&2
    exit 1
fi

# --- python venv: create on first run, refresh otherwise ---------------------
# A .venv is always regenerable from uv.lock, so this section is free to rebuild
# one that is missing or half-installed.
have_uv=0
if command -v uv >/dev/null 2>&1; then
    have_uv=1
fi

if [ "$have_uv" -eq 0 ] && [ ! -e "$VENV_PY" ]; then
    cat >&2 <<EOF
No virtualenv at '$VENV_PY' and 'uv' is not on PATH, so the launcher cannot
create one. First-time setup -- run these from the project root, then run this
launcher again:

  curl -LsSf https://astral.sh/uv/install.sh | sh   # install uv (or: brew install uv)
  uv sync                                           # install Python dependencies
  cp .env.example .env                              # then edit .env (at minimum HF_TOKEN)
EOF
    exit 1
fi

if [ "$have_uv" -eq 1 ]; then
    # uv hardlinks the packages it installs into the venv, and APFS does
    # hardlinks natively, so the install is a straight no-op when the lockfile
    # already matches.
    uv sync
    rc=$?
    if [ "$rc" -ne 0 ] && [ -d "$VENV_DIR" ]; then
        printf 'warning: uv sync failed (exit code %d) - the .venv may be half-installed. Deleting it and retrying once...\n' "$rc" >&2
        rm -rf "$VENV_DIR"
        uv sync
        rc=$?
    fi
    if [ "$rc" -ne 0 ]; then
        cat >&2 <<EOF
uv sync failed (exit code $rc) - see output above. The app cannot start
without its Python dependencies. Delete the .venv folder and run this launcher
again if it keeps failing; otherwise report the error above.
EOF
        exit 1
    fi
else
    printf 'warning: uv not on PATH - skipping uv sync (the .venv may be stale; run "uv sync" to refresh it).\n' >&2
fi

# --- .env: start from .env.example on first run ------------------------------
# The server reads this file itself, in Python (server/app/config.py), so the
# launcher only materialises it -- never source it here, which would leak every
# value into the environment and trip over whatever the shell does not like in
# the quoting. An existing .env is left completely alone: it is the user's, and
# it is where the real HF_TOKEN lives.
if [ ! -e .env ]; then
    if [ -e .env.example ]; then
        cp .env.example .env
        # The file is about to hold a token, so it must not be world-readable
        # on a machine that this repo is not the only thing on.
        chmod 600 .env
        printf 'Created .env from .env.example - the default login is admin/admin; add your HF_TOKEN before diarization will work.\n'
    else
        printf 'warning: no .env (and no .env.example) - running with built-in defaults.\n' >&2
    fi
fi

# --- install web deps if this is a fresh checkout ----------------------------
# One-off cost, so the guard is the directory itself, not the manifest: if
# node_modules is there, npm already has what it needs.
if [ ! -d web/node_modules ]; then
    printf 'Installing web dependencies (npm install)...\n'
    ( cd web && npm install )
    rc=$?
    if [ "$rc" -ne 0 ]; then
        printf 'error: npm install failed (exit code %d)\n' "$rc" >&2
        exit 1
    fi
fi

# --- build the web frontend if stale ----------------------------------------
# The build is regenerable from web/src, so the test is only "is anything in the
# sources newer than the last thing we produced?". BSD find has no -printf, so
# instead of comparing two newest-timestamps the predicate is the POSIX "-newer
# FILE" form against web/dist/index.html, which vite rewrites on every build
# (so its mtime stands for the build as a whole).
need_build=1
if [ -f web/dist/index.html ] && [ -d web/src ]; then
    stale=$(find web/src -type f -newer web/dist/index.html)
    [ -n "$stale" ] || need_build=0
fi
if [ "$need_build" -eq 1 ]; then
    printf 'Building web frontend (npm run build)...\n'
    ( cd web && npm run build )
    rc=$?
    if [ "$rc" -ne 0 ]; then
        printf 'error: npm run build failed (exit code %d)\n' "$rc" >&2
        exit 1
    fi
else
    printf 'web/dist is up to date.\n'
fi

# --- launch (no --reload in prod) -------------------------------------------
# uvicorn is started by importing its console entry point through the venv's
# python. This is the one launch form that holds on every platform: it does not
# go through the launcher script uv writes into the venv's bin (which depends on
# how uv generated it), and it does not require the package to ship a __main__
# module for "-m uvicorn" to find. Everything after the -c string arrives as
# sys.argv[1:], which is exactly what uvicorn.main.main() parses.
# No --reload: prod serves the code as it stands, and reloading would re-import
# the whole model stack on every source touch.
printf 'Starting media-transcription on 0.0.0.0:8000 (Ctrl+C to stop)...\n'
"$VENV_PY" -c 'from uvicorn.main import main; main()' server.app.main:app --host 0.0.0.0 --port 8000
rc=$?
if [ "$rc" -ne 0 ]; then
    printf 'uvicorn exited with code %d\n' "$rc" >&2
    exit "$rc"
fi

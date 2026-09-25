"""Root conftest: make the project root importable as the `server` package so
`pytest` (run via `uv run pytest` from the project root) can import
`server.app...` without needing the app installed."""
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

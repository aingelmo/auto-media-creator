"""Launch the local edl-agent web UI.

Usage: uv run scripts/run_web.py [--host HOST] [--port PORT]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-reload", action="store_true", help="disable autoreload")
    args = parser.parse_args()
    uvicorn.run(
        "edl_agent.web.app:app",
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
        reload_dirs=[str(Path(__file__).resolve().parent.parent / "src")],
    )


if __name__ == "__main__":
    main()

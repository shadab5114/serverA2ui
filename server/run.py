"""Entry point: `uv run python run.py [--port N]`. Always runs on a Selector event loop (see app/loops.py)."""

from __future__ import annotations

import argparse
import sys

import uvicorn

from app.config import settings


def main() -> None:
    # Windows consoles default to a legacy code page; the flow log uses ▶ │ └▶.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="A2UI GenUI playground backend (Python)")
    parser.add_argument("--port", type=int, default=settings.port, help="default: AGUI_PORT or 8090")
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        loop="app.loops:selector_loop_factory",
        log_level="warning",  # our own readable flow log replaces uvicorn's access log
    )


if __name__ == "__main__":
    main()

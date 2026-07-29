#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Server startup script for the CAD translation backend."""

from __future__ import annotations

import sys
from pathlib import Path

import uvicorn


project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.config import get_settings


def get_frontend_dist_path() -> Path:
    return project_root.parent / "frontend" / "dist"


def main() -> None:
    settings = get_settings()
    frontend_dist = get_frontend_dist_path()
    launch_url = f"http://{settings.HOST}:{settings.PORT}"

    print("=" * 60)
    print("CAD Translation Backend")
    print("=" * 60)
    print(f"Backend entry: {project_root / 'run_server.py'}")
    print(f"Frontend dist: {frontend_dist}")
    print(f"Server: {launch_url}")
    print(f"Docs: {launch_url}/api/docs")
    print(f"Async mode: {(settings.ASYNC_TASKS_MODE or 'auto').strip().lower()}")
    print(f"Debug: {'on' if settings.DEBUG else 'off'}")
    print("=" * 60)

    settings.get_upload_path()
    settings.get_output_path()
    settings.get_temp_path()
    settings.get_static_path()

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="debug" if settings.DEBUG else "info",
        access_log=True,
    )


if __name__ == "__main__":
    main()

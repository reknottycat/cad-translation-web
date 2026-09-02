#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backend import bridge for the ``cad-translate`` CLI.

The CLI does **not** keep its own snapshot copy of the CAD logic (that is the
"drifting ``lib/``" anti-pattern this refactor removes).  Instead it locates the
main repository's ``backend/`` package at runtime and imports the trusted
implementation from there, so the Web backend and the CLI always run the same
``app.*`` code.  Locating the backend is done in this one place only.

Search order (first match wins):
  1. ``CAD_TRANSLATION_BACKEND_DIR`` environment variable.
  2. A sibling ``backend/`` next to the installed package (development checkout).
  3. A ``backend/`` directory bundled inside the release delivery (scale_release).
  4. ``backend/`` found by walking up from the current working directory.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

# Repository root: <repo>/agent-harness/cad_translate/bridge.py -> parents[2].
_REPO_ROOT = Path(__file__).resolve().parents[2]

BACKEND_MARKER = "app"


def _candidates() -> list[Path]:
    configured = os.environ.get("CAD_TRANSLATION_BACKEND_DIR", "").strip()
    paths: list[Path] = []
    if configured:
        paths.append(Path(configured).expanduser())
    # Development checkout: <repo>/agent-harness/cad_translate/bridge.py
    paths.append(_REPO_ROOT / "backend")
    # Release delivery: walk up from the current directory so a bundled
    # backend/ anywhere on the path to the repo root is discovered.
    for ancestor in Path.cwd().parents:
        paths.append(ancestor / "backend")
    return paths


def find_backend_dir() -> Path:
    seen: set[str] = set()
    for candidate in _candidates():
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if (resolved / BACKEND_MARKER).is_dir():
            return resolved
    raise RuntimeError(
        "CAD backend (the directory that contains app/) was not found. Run the "
        "CLI from the repository root, set CAD_TRANSLATION_BACKEND_DIR to the "
        "backend directory, or reinstall the release bundle."
    )


def ensure_backend_importable() -> Path:
    """Insert the located ``backend/`` dir on ``sys.path`` (idempotent)."""
    backend_dir = find_backend_dir()
    backend_str = str(backend_dir)
    if backend_str not in sys.path:
        sys.path.insert(0, backend_str)
    return backend_dir


@lru_cache(maxsize=1)
def get_version() -> str:
    ensure_backend_importable()
    from app.version import __version__

    return __version__


@lru_cache(maxsize=1)
def get_settings():
    ensure_backend_importable()
    from app.config import get_settings as _get_settings

    return _get_settings()


@lru_cache(maxsize=1)
def get_runtime_config_service():
    ensure_backend_importable()
    from app.services.runtime_config_service import runtime_config_service

    return runtime_config_service


@lru_cache(maxsize=1)
def get_text_extractor():
    ensure_backend_importable()
    from app.functions.text_extractor import TextExtractor

    return TextExtractor()


@lru_cache(maxsize=1)
def get_dwg_converter():
    ensure_backend_importable()
    from app.functions.dwg_converter import DWGConverter

    settings = get_settings()
    return DWGConverter(
        converter_backend=settings.DWG_CONVERTER_BACKEND,
        dwg_auto_backends=settings.DWG_AUTO_BACKENDS,
        dwg_disabled_backends=settings.DWG_DISABLED_BACKENDS,
        oda_path=settings.ODA_FILE_CONVERTER_PATH,
        oda_output_version=settings.ODA_OUTPUT_VERSION,
        oda_output_format=settings.ODA_OUTPUT_FORMAT,
        cad_converter_timeout=settings.CAD_CONVERTER_TIMEOUT,
        libredwg_dwg2dxf_path=settings.LIBREDWG_DWG2DXF_PATH,
        libredwg_install_dir=settings.LIBREDWG_INSTALL_DIR,
        libredwg_download_url=settings.LIBREDWG_DOWNLOAD_URL,
        libredwg_auto_download=settings.LIBREDWG_AUTO_DOWNLOAD,
    )


@lru_cache(maxsize=1)
def get_text_applier():
    ensure_backend_importable()
    from app.functions.text_applier import TextApplier

    return TextApplier()


@lru_cache(maxsize=1)
def get_translator():
    ensure_backend_importable()
    from app.functions.translator import Translator

    return Translator()


@lru_cache(maxsize=1)
def get_llm_excel_processor():
    ensure_backend_importable()
    from app.services.llm.translation_service import llm_excel_processor

    return llm_excel_processor


@lru_cache(maxsize=1)
def get_llm_translation_service():
    ensure_backend_importable()
    from app.services.llm.translation_service import llm_translation_service

    return llm_translation_service

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Single-source dynamic ``version`` provider for the ``cad-translate`` CLI.

All static packaging metadata lives in the PEP 621 ``[project]`` table of
``pyproject.toml``.  ``version`` is declared ``dynamic`` there so that
setuptools delegates it to this file, which reads the one canonical SemVer
source ``backend/app/version.py`` at build time.  We never hard-code the
version in two places, so the CLI and the backend cannot drift (Issue #14).

Running ``python setup.py --name`` or an isolated ``python -m build
--wheel --sdist`` therefore needs the backend checkout to be reachable as
``<this-dir>/../backend/app/version.py`` (true in this monorepo and in the
delivery package, where ``agent-harness`` sits next to ``backend``).
"""
from __future__ import annotations

import re
from pathlib import Path

from setuptools import setup

ROOT = Path(__file__).resolve().parent
BACKEND_VERSION = ROOT.parent / "backend" / "app" / "version.py"

# Single canonical version, read from backend/app/version.py.
_version_match = re.search(
    r'^__version__\s*=\s*["\']([^"\']+)["\']',
    BACKEND_VERSION.read_text(encoding="utf-8"),
    re.MULTILINE,
)
if not _version_match:
    raise SystemExit("Could not parse version from backend/app/version.py")

setup(version=_version_match.group(1))

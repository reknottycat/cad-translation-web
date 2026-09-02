#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""``cad-translate`` — local CAD translation CLI.

This package is a thin, maintained facade over the main repository's
``backend/app`` trusted implementation.  It does not carry its own snapshot of
the CAD pipeline; instead :mod:`cad_translate.bridge` locates and imports the
backend at runtime so the CLI always runs the same code as the Web app.
"""
from __future__ import annotations

import sys as _sys

import structlog as _structlog

# Route backend structlog output to stderr so the CLI's stdout stays clean for
# human and ``--json`` output.  This runs at import time (before backend modules
# emit any logs) so it also applies when the CLI is driven through a test runner.
_structlog.configure(
    processors=[
        _structlog.processors.TimeStamper(fmt="iso"),
        _structlog.processors.StackInfoRenderer(),
        _structlog.processors.format_exc_info,
        _structlog.processors.ExceptionRenderer(),
        _structlog.processors.JSONRenderer(),
    ],
    wrapper_class=_structlog.make_filtering_bound_logger(30),  # INFO
    logger_factory=_structlog.PrintLoggerFactory(file=_sys.stderr),
)

# Make the bundled backend importable before any ``app.*`` import below runs.
from . import bridge as _bridge

_bridge.ensure_backend_importable()

__all__ = ["bridge"]

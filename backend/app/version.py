#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Canonical single version truth for the CAD translation project.

Every component -- the FastAPI backend, the ``cad-translate`` CLI package and
the runtime delivery metadata -- reads from this one constant so that no two
sources of truth can drift apart (see Issue #14).
"""
from __future__ import annotations

__version__ = "2.1.0"

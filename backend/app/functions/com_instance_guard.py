#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COM instance usability guard (shared by the CAD connection layer).

A race specific to live CAD hosts: when a *probe* (or any earlier client)
successfully ``Dispatch``-es a CAD instance and then ``Quit()``-s it, the CAD
process does not exit synchronously -- its shutdown is asynchronous, and its
Running Object Table (ROT) registration can linger for a short window.  If the
connection layer runs ``GetActiveObject`` inside that window it receives a
**stale active proxy** pointing at the half-shut-down CAD.  Such a proxy is not
``None`` and even a subsequent ``GetActiveObject`` returns it, yet touching its
COM surface (``Version`` / ``Documents``) raises, which later surfaces as an
``AttributeError``/``COMError`` on ``app.Version`` during conversion.

This module gives the connection layer a single, testable way to:

* **validate** that an acquired instance is genuinely usable by touching the
  members a conversion relies on (``Version`` and ``Documents``); and
* **prefer a fresh ``Dispatch``** over a stale ``GetActiveObject`` result so the
  connection does not bind to a dying instance the probe just quit.

No Windows COM is touched at import time and non-Windows/CI hosts can import it
safely.
"""

from __future__ import annotations

from typing import Optional


def instance_is_usable(instance, require_documents: bool = True) -> bool:
    """Return True only if ``instance`` exposes a live, reachable COM surface.

    Touches the same members the connection layer relies on later (``Version``
    for a CAD application, and ``Documents``).  A stale proxy pointing at a
    just-quit instance raises when these are read, so it is rejected here
    instead of being accepted as a successful connection.
    """
    if instance is None:
        return False
    # Reading each attribute forces a real COM cross-process call; on a dead /
    # stale proxy this raises instead of returning a cached value.
    try:
        _ = getattr(instance, "Version")
        if require_documents:
            _ = getattr(instance, "Documents")
        return True
    except Exception:  # noqa: BLE001 - COM raises generic exceptions
        return False


def acquire_usable_instance(
    client,
    prog_id: str,
    *,
    require_documents: bool = True,
    stale_hint: Optional[list] = None,
):
    """Activate ``prog_id`` returning only an instance proven usable.

    Order of attempts (all on the current COM thread/apartment):

    1. ``GetActiveObject`` -- attaches an already-running CAD owned by the user.
       If the returned instance is **stale** (a probe just quit it) it is
       rejected and we fall through rather than binding to a dying process.
    2. ``Dispatch`` -- starts a fresh instance; also validated before use.

    Returns ``(kind, instance)`` where ``kind`` is ``"active"`` (a usable
    already-running instance was attached), ``"dispatch"`` (a usable fresh
    instance was started and must later be quit by the caller), or ``(None,
    None)`` when no attempt yielded a usable instance (``stale_hint``, when
    given, records why a GetActiveObject result was discarded).
    """
    # 1) Attach an already-running CAD, but only if it is genuinely usable.
    try:
        instance = client.GetActiveObject(prog_id)
    except Exception:
        instance = None
    if instance is not None:
        if instance_is_usable(instance, require_documents=require_documents):
            return "active", instance
        # Stale active proxy (probe quit the instance, ROT entry lingers).
        if stale_hint is not None:
            stale_hint.append(
                f"GetActiveObject for {prog_id} returned a stale/unusable "
                "proxy (Version/Documents not reachable); re-dispatching a "
                "fresh instance"
            )
        instance = None

    # 2) Fresh Dispatch is authoritative (never returns a stale ROT proxy).
    try:
        instance = client.Dispatch(prog_id)
    except Exception:
        return None, None
    if not instance_is_usable(instance, require_documents=require_documents):
        return None, None
    return "dispatch", instance


__all__ = ["instance_is_usable", "acquire_usable_instance"]

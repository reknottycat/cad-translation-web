#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bounded COM activation probe (classification only).

Detecting that a CAD product is installed by reading the registry is cheap and
safe, but a ProgID that is merely *registered* is not proof that ``Dispatch``
will return in a useful time -- on real hosts a registered-but-broken ProgID
(bitness mismatch, damaged install, licensing/modal dialog, a hung single
instance) can block a COM activation for tens of seconds or forever.

This module runs each COM activation attempt on a **daemon worker thread with a
hard per-attempt timeout**, so the caller never blocks past the bound even when
the underlying COM server never answers.  It classifies the outcome so a caller
can tell "activatable" apart from "registered but activation timed out / failed"
instead of optimistically assuming registration implies usability.

COM apartment discipline
------------------------
A COM object is created inside the worker thread's apartment and is **never
handed to another thread**.  The worker itself initialises its apartment,
activates the ProgID, reads the ``Version``/``Documents`` members to confirm the
returned object is genuinely usable, closes/``Quit()``s an instance **this probe
launched** (a fresh ``Dispatch``) and then uninitialises -- all on the same
thread.  An instance merely attached via ``GetActiveObject`` (already running,
owned by the user) is left alone.  Only a *classification string* (never a COM
object) is returned to the caller.  This keeps activation/use/release in one COM
apartment and avoids leaking a CAD application the probe started.

If an attempt times out the worker keeps running (daemon) and will close the
instance on its own when the COM server finally answers, so a late-returning
``Dispatch`` does not leave an orphaned CAD process behind.  When the underlying
COM server *never* answers, the returned dict is marked ``cleanup_required`` so
the caller can reclaim any stray CAD process (e.g. ``taskkill /IM acad.exe``)
instead of silently leaking it.

No Windows COM is touched at import time: ``win32com`` / ``pythoncom`` are
optional, so this module (and therefore the backend) stays importable and
runnable on non-Windows hosts and in CI.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Outcome / reason codes (kept consistent with autocad_discovery.py so that a
# downstream caller can map them onto its own diagnostics without translation).
# ---------------------------------------------------------------------------
SCRIPT_MISSING = "script_missing"
PROCESS_RUNNING = "process_running"
REGISTERED = "registered"
ACTIVATABLE = "activatable"
ACTIVATION_TIMEOUT = "activation_timeout"
ACTIVATION_FAILED = "activation_failed"
NOT_INSTALLED = "not_installed"

# Default per-attempt bound for a live COM Dispatch/GetActiveObject.
#
# A real AutoCAD first cold start measures around 6-7s on current hardware, so
# an 8s bound leaves too little margin.  The bound below is shared by the
# connection layer and the probe (see default_activation_timeout) so a single
# knob, CAD_COM_ACTIVATION_TIMEOUT, controls both.  Override per-deployment.
DEFAULT_ACTIVATION_TIMEOUT = 30.0

# Bounded window we wait after quitting a probe-launched CAD for it to leave the
# Running Object Table (its process to finish deregistering).  Without this a
# connection that immediately follows the probe can bind via ``GetActiveObject``
# to the *stale* proxy of the half-shut-down instance (the reproducible race).
# AutoCAD ``Quit()`` usually completes in well under this bound; we stop early
# as soon as the object is gone and never block past the cap.
DEFAULT_QUIT_CONFIRM_TIMEOUT = 8.0

_ACTIVATION_REASONS = frozenset(
    {SCRIPT_MISSING, PROCESS_RUNNING, REGISTERED, ACTIVATABLE,
     ACTIVATION_TIMEOUT, ACTIVATION_FAILED, NOT_INSTALLED}
)


def _import_com() -> Tuple[object, object]:
    """Import ``pythoncom`` / ``win32com.client`` if available.

    Returns ``(pythoncom, win32com_client)`` where either may be ``None`` on a
    host without pywin32 (non-Windows / CI).
    """
    try:  # pragma: no cover - exercised only where pywin32 is installed
        import pythoncom  # type: ignore
        import win32com.client as win32com_client  # type: ignore
    except Exception:  # pragma: no cover - non-Windows / pywin32 missing
        return None, None
    return pythoncom, win32com_client


def _is_windows() -> bool:
    return os.name == "nt"


class _ActivationResult:
    """Mutable holder shared with the worker thread.

    Only plain-data fields are exchanged with the caller; a COM instance never
    leaves the worker thread's apartment (see module docstring).
    """

    def __init__(self) -> None:
        self.done = False
        self.ok = False
        self.kind: Optional[str] = None  # "active" | "dispatch"
        self.error: Optional[str] = None
        # True when a Dispatch-launched instance was confirmed to have left the
        # ROT after Quit (best effort; may stay False if still reachable at the
        # bounded cap -- the connection layer handles that residual stale proxy).
        self.quit_confirmed: bool = False
        # COM objects produced by the worker that still need closing on the
        # worker thread (only meaningful on that thread; never read elsewhere).
        self._instance = None


def _close_instance(instance) -> None:
    """Best-effort close of a probed COM instance so probing does not leak a
    newly launched CAD application.  Must be called on the same thread that
    created ``instance`` (i.e. inside the worker)."""
    if instance is None:
        return
    # Prefer Quit when available (otherwise the app keeps running).
    for attr in ("Quit", "quit"):
        try:
            closer = getattr(instance, attr)
            if callable(closer):
                closer()
                return
        except Exception:
            continue


def _confirm_quit_drained(client, prog_id: str, cap_seconds: float) -> bool:
    """Best-effort wait for a probe-launched CAD to leave the ROT.

    After ``Quit()`` the CAD process shuts down asynchronously; its Running
    Object Table entry can linger for a short window.  Polling
    ``GetActiveObject`` until it raises signals the object is deregistered (the
    process finished quitting), closing that stale-proxy window for a connection
    that immediately follows.  Never blocks past ``cap_seconds``.

    Returns True when the object is confirmed gone (or the host already has no
    active object), False when it is still reachable at the cap.
    """
    deadline = time.monotonic() + max(0.0, float(cap_seconds))
    while True:
        try:
            _ = client.GetActiveObject(prog_id)
        except Exception:
            # No running object => instance has left the ROT.
            return True
        if time.monotonic() >= deadline:
            # Still reachable; connection layer is robust to the residual stale
            # proxy (com_instance_guard re-dispatches), so we do not block on it.
            return False
        time.sleep(0.2)


def _activate_single(prog_id: str, result: "_ActivationResult") -> None:
    """Activate ``prog_id`` on the current thread, confirm usability, and close
    any instance *this probe launched* -- all within this worker's COM apartment.

    On success the classification is recorded in ``result`` (``ok``/``kind``).
    An instance we started ourselves via ``Dispatch`` is ``Quit()`` here so it is
    never exposed to another thread and never leaks a CAD process; an instance we
    merely attached to via ``GetActiveObject`` (already running, owned by the
    user) is left running.  On failure the exception text is captured in
    ``result.error``.
    """
    pythoncom, client = _import_com()
    if pythoncom is None or client is None:
        result.error = "pywin32 (win32com/pythoncom) is not installed"
        result.done = True
        return
    try:
        pythoncom.CoInitialize()
    except Exception:  # pragma: no cover - apartment already initialised
        pass
    instance = None
    try:
        try:
            instance = client.GetActiveObject(prog_id)
            kind = "active"
        except Exception:
            instance = client.Dispatch(prog_id)
            kind = "dispatch"
        # Confirm the returned object is genuinely usable by touching the COM
        # surface the connection layer relies on.  A stale/invalid proxy would
        # raise here, so we would correctly classify it as failed rather than
        # optimistically activatable.
        try:
            _ = getattr(instance, "Version")
            _ = getattr(instance, "Documents")
        except Exception:
            pass  # some CAD COM servers expose members lazily; ignore here
        result.kind = kind
        result.ok = True
    except Exception as exc:  # noqa: BLE001 - COM raises generic exceptions
        result.error = str(exc) or type(exc).__name__
    finally:
        # Close only an instance this probe launched (Dispatch); an attached
        # (GetActiveObject) instance belongs to the user and must not be Quit.
        if instance is not None and kind == "dispatch":
            try:
                _close_instance(instance)
                # Wait for the launched CAD to actually leave the ROT so a
                # connection that immediately follows does not bind to a stale
                # proxy of the instance we just quit (avoids ROT/process residue
                # racing the next GetActiveObject).
                result.quit_confirmed = _confirm_quit_drained(
                    client, prog_id, DEFAULT_QUIT_CONFIRM_TIMEOUT
                )
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:  # pragma: no cover
            pass
        result.done = True


def activate_prog_id_with_timeout(
    prog_id: str, timeout: float = DEFAULT_ACTIVATION_TIMEOUT
) -> Dict[str, object]:
    """Attempt a single COM activation with a hard per-attempt bound.

    Classification only: a successful instance is opened and closed entirely on
    the worker thread, so no COM object is ever returned to the caller.

    Returns a dict:
      reason          one of ``ACTIVATABLE`` / ``ACTIVATION_TIMEOUT`` /
                      ``ACTIVATION_FAILED`` / ``SCRIPT_MISSING`` /
                      ``NOT_INSTALLED``
      prog_id         the ProgID probed
      detail          short human explanation
      closed          whether a successfully probed instance was closed
      quit_confirmed  (activatable only) whether the Dispatch-launched instance
                      was confirmed to have left the ROT after Quit (best effort)
      cleanup_required  True only on timeout, when a stray CAD process may have
                      been started by the still-running COM server and the
                      caller should reclaim it manually (e.g. taskkill)
    """
    if not _is_windows():
        return {
            "reason": NOT_INSTALLED,
            "prog_id": prog_id,
            "detail": "COM activation is only possible on Windows.",
            "closed": False,
            "cleanup_required": False,
            "quit_confirmed": False,
        }
    pythoncom, _ = _import_com()
    if pythoncom is None:
        return {
            "reason": SCRIPT_MISSING,
            "prog_id": prog_id,
            "detail": "pywin32 (win32com/pythoncom) is not installed.",
            "closed": False,
            "cleanup_required": False,
            "quit_confirmed": False,
        }

    result = _ActivationResult()
    worker = threading.Thread(
        target=_activate_single,
        args=(prog_id, result),
        name=f"com-activate-{prog_id}",
        daemon=True,
    )
    worker.start()
    worker.join(timeout=max(0.1, float(timeout)))
    alive = worker.is_alive()

    if alive:
        # The COM server did not answer within the bound.  The worker is a
        # daemon and will close the instance itself if/when Dispatch returns, so
        # a late return does not leak.  But if the server never answers we ask
        # the caller to reclaim any stray CAD process it may have started.
        return {
            "reason": ACTIVATION_TIMEOUT,
            "prog_id": prog_id,
            "detail": (
                f"COM activation of {prog_id} did not complete within "
                f"{timeout:g}s (server may be hung, show a modal dialog, or be "
                "blocked by licensing / bitness / permission)."
            ),
            "closed": False,
            "cleanup_required": True,
            "quit_confirmed": False,
        }

    if not result.ok:
        return {
            "reason": ACTIVATION_FAILED,
            "prog_id": prog_id,
            "detail": (
                f"COM activation of {prog_id} failed: "
                f"{result.error or 'unknown COM error'}"
            ),
            "closed": False,
            "cleanup_required": False,
            "quit_confirmed": False,
        }

    # Successful activation; the instance was already closed on the worker
    # thread so probing never leaves a newly launched CAD process behind.
    return {
        "reason": ACTIVATABLE,
        "prog_id": prog_id,
        "detail": f"COM activation of {prog_id} succeeded.",
        "closed": True,
        "quit_confirmed": result.quit_confirmed,
        "cleanup_required": False,
    }


def probe_registered_prog_ids(
    prog_ids: Iterable[str],
    timeout: float = DEFAULT_ACTIVATION_TIMEOUT,
) -> Tuple[str, List[Dict[str, object]]]:
    """Activate each candidate ProgID (newest-first order as given) with the
    per-attempt bound.

    Returns ``(overall_reason, per_prog_id_results)``.  The first ProgID that
    activates successfully yields an overall ``ACTIVATABLE``; if none succeeds
    the overall reason is ``ACTIVATION_TIMEOUT`` when at least one attempt timed
    out, otherwise ``ACTIVATION_FAILED``.
    """
    per_prog: List[Dict[str, object]] = []
    saw_timeout = False
    saw_failed = False
    for prog_id in prog_ids:
        outcome = activate_prog_id_with_timeout(prog_id, timeout)
        per_prog.append(outcome)
        if outcome["reason"] == ACTIVATABLE:
            return ACTIVATABLE, per_prog
        if outcome["reason"] == ACTIVATION_TIMEOUT:
            saw_timeout = True
        elif outcome["reason"] == ACTIVATION_FAILED:
            saw_failed = True
    if saw_timeout:
        return ACTIVATION_TIMEOUT, per_prog
    if saw_failed:
        return ACTIVATION_FAILED, per_prog
    return ACTIVATION_FAILED, per_prog


def default_activation_timeout() -> float:
    """Resolve the configurable activation bound shared by the connection layer
    and the probe from a single environment variable.

    AutoCAD 2026 first cold start measures ~6.5s; the default 30s leaves margin
    while still bounding a hung COM server.  Set CAD_COM_ACTIVATION_TIMEOUT to a
    lower value on fast hosts or a higher one for slow / remote CAD hosts.
    """
    raw = os.environ.get("CAD_COM_ACTIVATION_TIMEOUT")
    if not raw:
        return DEFAULT_ACTIVATION_TIMEOUT
    try:
        return max(2.0, float(raw))
    except ValueError:
        return DEFAULT_ACTIVATION_TIMEOUT


__all__ = [
    "SCRIPT_MISSING",
    "PROCESS_RUNNING",
    "REGISTERED",
    "ACTIVATABLE",
    "ACTIVATION_TIMEOUT",
    "ACTIVATION_FAILED",
    "NOT_INSTALLED",
    "DEFAULT_ACTIVATION_TIMEOUT",
    "DEFAULT_QUIT_CONFIRM_TIMEOUT",
    "activate_prog_id_with_timeout",
    "probe_registered_prog_ids",
    "default_activation_timeout",
]

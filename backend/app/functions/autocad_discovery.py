#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AutoCAD COM discovery & diagnostics.

Pure discovery helpers for AutoCAD COM ProgIDs/registration so the backend can
decide *before* attempting a conversion whether an AutoCAD COM bridge is
plausibly available on this Windows host, and so a conversion can give an
actionable reason when it is not.

This module deliberately performs **no live COM activation**: that belongs to
the connection layer (``app.services.autocad_converter``) which runs in a
subprocess under a timeout.  Here we only read the registry and process table,
which is fast and safe to call from the main server process.  ``win32com`` /
``winreg`` are optional at import time so non-Windows hosts stay importable.
"""

from __future__ import annotations

import os
import re
from typing import Dict, Iterator, List, Set, Tuple

try:  # pragma: no cover - exercised on Windows only
    import winreg
except Exception:  # pragma: no cover - non-Windows / missing module
    winreg = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Reason codes (shared by detection and diagnostics)
# ---------------------------------------------------------------------------
# Python COM bridge script is present but the bridge executable/py is missing.
SCRIPT_MISSING = "script_missing"
# An AutoCAD process (acad.exe) is currently running.
PROCESS_RUNNING = "process_running"
# A versioned ProgID is registered but no process is running yet.
REGISTERED = "registered"
# Registered and live COM activation succeeded (reported by connection layer).
ACTIVATABLE = "activatable"
# Registration exists but COM activation failed (permission / bits / damage).
ACTIVATION_FAILED = "activation_failed"
# No registration and no process -> not installed on this host.
NOT_INSTALLED = "not_installed"
# Found only in a mismatched 32/64 registry view -> likely bits mismatch.
REGISTRATION_VIEW_MISMATCH = "registration_view_mismatch"
# Fallback internal marker when the backend is not a known COM backend.
UNSUPPORTED = "unsupported"

# Baseline ProgIDs newest-first.  Registry enumeration extends these so future
# AutoCAD releases (which follow the ``AutoCAD.Application.<major>[.<minor>]``
# convention) are recognised without a code change.
AUTOCAD_BASELINE_PROGIDS: List[str] = [
    "AutoCAD.Application",  # unversioned alias -> points at newest registered
    "AutoCAD.Application.26.1",  # (future / 2024+ minor)
    "AutoCAD.Application.26",    # 2024
    "AutoCAD.Application.25.1",  # 2023.1
    "AutoCAD.Application.25",    # 2023
    "AutoCAD.Application.24.1",  # 2022.1
    "AutoCAD.Application.24",    # 2022
    "AutoCAD.Application.23.1",  # 2020/2021.1
    "AutoCAD.Application.23",    # 2020/2021
    "AutoCAD.Application.22",    # 2018/2019
    "AutoCAD.Application.21.1",
    "AutoCAD.Application.21",
    "AutoCAD.Application.20.1",
    "AutoCAD.Application.20",
]

# Regular expression matching AutoCAD versioned ProgIDs of the form
# ``AutoCAD.Application.<major>`` or ``AutoCAD.Application.<major>.<minor>``.
_AUTOCAD_VERSIONED_RE = re.compile(r"^AutoCAD\.Application\.\d+(?:\.\d+)?$", re.IGNORECASE)


def _registry_roots() -> Iterator[Tuple[int, str]]:
    """Yield ``(hive, subkey)`` pairs mirroring HKCR in a given bitness view.

    HKCR is a merged view of ``HKLM\\Software\\Classes`` + ``HKCU\\Software\\
    Classes``.  Opening those directly lets us pass a 32/64-bit view flag so we
    can tell *which* view registered a ProgID (and thus whether a bits mismatch
    is the likely cause of a later activation failure).
    """
    if winreg is None:
        return iter(())
    yield winreg.HKEY_LOCAL_MACHINE, r"Software\Classes"
    yield winreg.HKEY_CURRENT_USER, r"Software\Classes"


def _view_flags() -> Tuple[int, ...]:
    """Return the view-access flags to probe, best-effort for current python.

    On a 64-bit Python, both the 64-bit and 32-bit WOW64 views are enumerable.
    On a 32-bit Python only the 32-bit view is reachable.
    """
    if winreg is None:
        return ()
    native = getattr(winreg, "KEY_WOW64_64KEY", 0)
    wow32 = getattr(winreg, "KEY_WOW64_32KEY", 0)
    flags = [0]
    # 0 (KEY_WOW64_64KEY on 64-bit python, else native).  Add explicit flags only
    # when constants exist so the module works on any Python.
    if native:
        flags.append(native)
    if wow32:
        flags.append(wow32)
    return tuple(dict.fromkeys(flags))  # de-dup, preserve order


def _iter_registered_autocad_keys() -> Iterator[Tuple[str, int]]:
    """Yield ``(prog_id, view_flag)`` for every AutoCAD ProgID seen in the
    registry, across the reachable 32/64 views, de-duplicated by ProgID."""
    if winreg is None:
        return
    seen: Set[str] = set()
    view_flags = _view_flags()
    for hive, subkey in _registry_roots():
        for view_flag in view_flags:
            try:
                with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ | view_flag) as root:
                    index = 0
                    while True:
                        try:
                            name = winreg.EnumKey(root, index)
                        except OSError:
                            break
                        index += 1
                        if _AUTOCAD_VERSIONED_RE.match(name) or name.lower() == "autocad.application":
                            key = name.lower()
                            if key not in seen:
                                seen.add(key)
                                yield name, view_flag
            except OSError:
                continue


def discovered_autocad_progids() -> List[str]:
    """Return the ordered candidate AutoCAD ProgIDs to attempt, newest first.

    - On a host where the registry is not inspectable (non-Windows / no
      ``winreg``) returns ``[]``: there is nothing we can meaningfully try.
    - On Windows, returns the registered versioned ProgIDs (newest first) plus
      the unversioned ``AutoCAD.Application`` alias.  When nothing is registered
      it returns the static baseline so the connection layer can still probe and
      produce a precise "registered but activation failed" diagnostic instead of
      silently treating a damaged registration as "not installed".
    """
    if winreg is None:
        return []

    registered = list(dict.fromkeys(pid for pid, _ in _iter_registered_autocad_keys()))
    baseline_lower = [p.lower() for p in AUTOCAD_BASELINE_PROGIDS]

    # de-dup keys are always lower-cased so that AutoCAD ProgIDs registered under
    # different registry views with differing casing collapse into one entry.
    def _dedup(candidates) -> List[str]:
        out: List[str] = []
        seen: Set[str] = set()
        for pid in candidates:
            key = pid.lower()
            if key not in seen:
                seen.add(key)
                out.append(pid)
        return out

    versioned = _dedup(
        pid for pid in registered
        if pid != "autocad.application" and _AUTOCAD_VERSIONED_RE.match(pid)
    )
    versioned.sort(key=_version_sort_key, reverse=True)
    merged = versioned

    if any(pid.lower() == "autocad.application" for pid in registered):
        merged.append("autocad.application")

    if not merged:
        # Nothing registered (or registry empty): still return the baseline so a
        # subsequent COM activation failure can be attributed to a bits/permission
        # or damaged-registration problem rather than "not installed".
        merged = list(baseline_lower)
    else:
        # Append any baseline versioned entries not yet covered (older historical
        # versions) purely for diagnostic completeness.  The membership test is
        # case-insensitive so we never emit a lower-case duplicate of an already
        # listed CamelCase entry (nor vice versa).
        present = {pid.lower() for pid in merged}
        merged.extend(pid for pid in baseline_lower if pid.lower() not in present)

    return merged


def _version_sort_key(prog_id: str) -> Tuple[int, int]:
    """Sort a versioned ProgID by its ``(major, minor)`` numbers."""
    match = re.search(r"\.(\d+)(?:\.(\d+))?$", prog_id)
    if not match:
        return (0, 0)
    return (int(match.group(1)), int(match.group(2)) if match.group(2) else 0)


def _is_windows() -> bool:
    """True when running on Windows.  Kept as a tiny helper so unit tests can
    simulate the Windows registry/process behaviour without mutating the global
    ``os.name`` (which would corrupt pathlib/pytest internals)."""
    return os.name == "nt"


def any_autocad_registered() -> bool:
    """True if any AutoCAD ProgID is present in the registry."""
    if winreg is None:
        return False
    for _, _ in _iter_registered_autocad_keys():
        return True
    return False


def _running_autocad_process() -> bool:
    """Return True if an acad.exe process is currently running (Windows only)."""
    if not _is_windows():
        return False
    import subprocess
    from csv import reader as csv_reader
    from io import StringIO

    try:
        completed = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except Exception:
        return False
    if completed.returncode != 0:
        return False
    for row in csv_reader(StringIO(completed.stdout)):
        if row and row[0].strip().lower() == "acad.exe":
            return True
    return False


def probe_autocad_presence(
    bridge_script_present: bool = True,
    *,
    registered: Optional[bool] = None,
    running: Optional[bool] = None,
) -> Dict[str, object]:
    """Classify AutoCAD COM availability into a single actionable reason.

    ``bridge_script_present`` is whether ``app/services/autocad_converter.py``
    exists on disk.  ``registered``/``running`` are optional overrides used in
    tests; when ``None`` they are probed live (registry + tasklist).

    Return keys:
      reason        one of the module-level reason codes
      prog_ids      ordered candidate ProgIDs for connection
      any_registered
      any_running
      actionable     a short human message
    """
    if not bridge_script_present:
        reason = SCRIPT_MISSING
    else:
        any_registered = any_autocad_registered() if registered is None else registered
        any_running = _running_autocad_process() if running is None else running
        if any_running:
            reason = PROCESS_RUNNING
        elif any_registered:
            reason = REGISTERED
        else:
            reason = NOT_INSTALLED

    prog_ids = discovered_autocad_progids()
    return {
        "reason": reason,
        "prog_ids": prog_ids,
        "any_registered": (any_autocad_registered() if registered is None else registered)
        if bridge_script_present
        else False,
        "any_running": (_running_autocad_process() if running is None else running)
        if bridge_script_present
        else False,
        "actionable": _actionable(reason),
    }


def _actionable(reason: str) -> str:
    mapping = {
        SCRIPT_MISSING: (
            "AutoCAD COM bridge script is missing (app/services/autocad_converter.py). "
            "Reinstall/repair the backend package."
        ),
        PROCESS_RUNNING: "AutoCAD is running; conversion may proceed via COM.",
        REGISTERED: "AutoCAD is installed and registered; conversion may proceed via COM.",
        ACTIVATABLE: "AutoCAD is installed and COM activation succeeded.",
        ACTIVATION_FAILED: (
            "AutoCAD is registered but COM activation failed. Check bitness match, "
            "permissions, and that the installation is not damaged; or install AutoCAD "
            "and register its COM server."
        ),
        NOT_INSTALLED: (
            "No AutoCAD COM registration or acad.exe process was detected on this host. "
            "Install/register AutoCAD, or configure another DWG backend (ODA / LibreDWG)."
        ),
        REGISTRATION_VIEW_MISMATCH: (
            "AutoCAD registration was found only in a different 32/64-bit registry view "
            "than this Python backend; install the matching AutoCAD bitness."
        ),
        UNSUPPORTED: "Backend is not a supported COM backend.",
    }
    return mapping.get(reason, reason)


__all__ = [
    "AUTOCAD_BASELINE_PROGIDS",
    "discovered_autocad_progids",
    "any_autocad_registered",
    "probe_autocad_presence",
    "SCRIPT_MISSING",
    "PROCESS_RUNNING",
    "REGISTERED",
    "ACTIVATABLE",
    "ACTIVATION_FAILED",
    "NOT_INSTALLED",
    "REGISTRATION_VIEW_MISMATCH",
    "UNSUPPORTED",
]

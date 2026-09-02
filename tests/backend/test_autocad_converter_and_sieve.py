#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for AutoCAD converter connection (mock win32com) and the auto-backend
sieving logic in DWGConverter (mock discovery/process)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Stub win32com so the service module can be imported on a non-Windows host.
# ---------------------------------------------------------------------------
def _install_win32com_stub():
    if "win32com" in sys.modules:
        return sys.modules["win32com"]
    client = types.ModuleType("win32com.client")
    client.GetActiveObject = None
    client.Dispatch = None
    win32com = types.ModuleType("win32com")
    win32com.client = client
    sys.modules["win32com"] = win32com
    sys.modules["win32com.client"] = client
    return win32com


_install_win32com_stub()

def _script_path_exists(_self, filename):
    import tempfile
    d = Path(tempfile.gettempdir()) / "cad_test_scripts"
    d.mkdir(parents=True, exist_ok=True)
    f = d / filename
    f.touch(exist_ok=True)
    return f


from app.services import autocad_converter as ac_mod  # noqa: E402
from app.functions.dwg_converter import DWGConverter  # noqa: E402
from app.functions import com_activation_probe as cp_mod  # noqa: E402
from app.functions import autocad_discovery as disc  # noqa: E402


@pytest.fixture
def win32com_client(monkeypatch):
    client = sys.modules["win32com.client"]
    # Default: no instance, Dispatch always fails.
    client.GetActiveObject = lambda prog_id: (_ for _ in ()).throw(RuntimeError("no active"))
    client.Dispatch = lambda prog_id: (_ for _ in ()).throw(RuntimeError("activation failed"))
    yield client


# --------------------------- service connection -----------------------------

def test_service_uses_discovered_future_progid(monkeypatch, win32com_client):
    """Newer versioned ProgIDs beyond the static baseline are attempted."""
    called = []
    registered_found = ["AutoCAD.Application.26.1", "AutoCAD.Application.26"]
    monkeypatch.setattr(
        disc, "discovered_autocad_progids", lambda: list(registered_found)
    )
    monkeypatch.setattr(disc, "any_autocad_registered", lambda: True)

    converter = ac_mod.AutoCADConverter()

    def fake_get_active(prog_id):
        called.append(prog_id)
        raise RuntimeError("not active")
    win32com_client.GetActiveObject = fake_get_active

    def fake_dispatch(prog_id):
        called.append(prog_id)
        if prog_id == "AutoCAD.Application.26":
            # Real AutoCAD always exposes Version and Documents; the connection
            # layer now validates both before accepting an instance (a stale
            # proxy lacks a live surface).  Reflect that in the fake.
            app = types.SimpleNamespace(
                Visible=True,
                Version="26.0s (LMS Tech)",
                Documents=object(),
            )
            return app
        raise RuntimeError("activation failed")

    win32com_client.Dispatch = fake_dispatch
    assert converter.connect_to_cad() is True
    assert converter.connected is True
    # 26.1 tried before 26, and a future version was recognised.
    assert called[0] == "AutoCAD.Application.26.1"


def test_service_activation_failure_diagnostic(monkeypatch, win32com_client):
    """Registered-but-activation-failure yields a clear actionable diagnostic."""
    monkeypatch.setattr(disc, "any_autocad_registered", lambda: True)
    converter = ac_mod.AutoCADConverter()
    assert converter.connect_to_cad() is False
    assert converter.last_error is not None
    assert "activation failed" in converter.last_error.lower() or "registered" in converter.last_error.lower()


def test_service_not_installed_diagnostic(monkeypatch, win32com_client):
    monkeypatch.setattr(disc, "any_autocad_registered", lambda: False)
    converter = ac_mod.AutoCADConverter()
    assert converter.connect_to_cad() is False
    assert converter.last_error is not None
    assert "no autocad" in converter.last_error.lower() or "install/register" in converter.last_error.lower()


# --------------------------- auto-backend sieving ---------------------------


def test_sieve_keeps_registered_autocad(monkeypatch):
    c = DWGConverter(dwg_auto_backends="haochen_com,autocad_com,oda")
    # Registry presence + a *confirmed* activation means the backend is kept.
    c.com_activation_probe_enabled = False  # rely on registration alone here
    # mock inspect helper level: simpler to just patch _registered_prog_ids/_running
    monkeypatch.setattr(DWGConverter, "_running_process_names", lambda self: set())
    monkeypatch.setattr(DWGConverter, "_registered_prog_ids", lambda self: {"autocad.application.26", "gstarcad.application"})
    monkeypatch.setattr(disc, "discovered_autocad_progids", lambda: ["AutoCAD.Application.26", "GStarCAD.Application"])
    monkeypatch.setattr(DWGConverter, "_service_script_path", _script_path_exists)
    sel = c._select_auto_backends()
    # oda not found -> binary_missing but kept as binary fallback chain element.
    assert "autocad_com" in sel
    assert "haochen_com" in sel


def test_sieve_drops_registered_but_activation_timeout(monkeypatch):
    """A registered-but-hung 浩辰/中望 backend must not be kept first in the
    auto chain just because its ProgID is present in the registry."""
    c = DWGConverter(dwg_auto_backends="haochen_com,autocad_com,oda")
    monkeypatch.setattr(DWGConverter, "_running_process_names", lambda self: set())
    monkeypatch.setattr(DWGConverter, "_registered_prog_ids", lambda self: {"gstarcad.application", "autocad.application.26"})
    monkeypatch.setattr(disc, "discovered_autocad_progids", lambda: ["AutoCAD.Application.26"])
    monkeypatch.setattr(DWGConverter, "_service_script_path", _script_path_exists)
    monkeypatch.setattr(DWGConverter, "_candidate_oda_paths", lambda self: iter([Path("/opt/ODAFileConverter.exe")]))
    # Simulate that the haochen activation times out but AutoCAD activates fine.
    def fake_probe(self, backend):
        return "activation_timeout" if backend == "haochen_com" else "activatable"
    monkeypatch.setattr(DWGConverter, "_probe_com_activation", fake_probe)
    sel = c._select_auto_backends()
    assert "haochen_com" not in sel
    assert "autocad_com" in sel
    # ODA binary present -> kept as fallback.
    assert "oda" in sel


def test_inspect_reports_activation_timeout_reason(monkeypatch):
    c = DWGConverter(dwg_auto_backends="autocad_com")
    monkeypatch.setattr(DWGConverter, "_running_process_names", lambda self: set())
    monkeypatch.setattr(DWGConverter, "_registered_prog_ids", lambda self: {"autocad.application.26"})
    monkeypatch.setattr(disc, "discovered_autocad_progids", lambda: ["AutoCAD.Application.26"])
    monkeypatch.setattr(DWGConverter, "_service_script_path", _script_path_exists)
    monkeypatch.setattr(DWGConverter, "_probe_com_activation", lambda self, backend: "activation_timeout")
    info = c.inspect_backends()["autocad_com"]
    assert info["reason"] == "activation_timeout"
    assert "actionable" in info and info["actionable"]


def test_sieve_fallback_chain_kept_when_all_removed(monkeypatch):
    """If every COM backend is sieved out but something is configured, the
    original ordered chain is preserved for a descriptive error."""
    c = DWGConverter(dwg_auto_backends="haochen_com,autocad_com")
    monkeypatch.setattr(DWGConverter, "_running_process_names", lambda self: set())
    monkeypatch.setattr(DWGConverter, "_registered_prog_ids", lambda self: {"gstarcad.application", "autocad.application.26"})
    monkeypatch.setattr(DWGConverter, "_service_script_path", _script_path_exists)
    monkeypatch.setattr(DWGConverter, "_probe_com_activation", lambda self, backend: "activation_failed")
    sel = c._select_auto_backends()
    # Both COM backends are unusable; the configured chain is kept so the
    # conversion reports a descriptive per-backend error.
    assert sel == ["haochen_com", "autocad_com"]


def test_sieve_drops_not_detected_com_but_keeps_oda(monkeypatch):
    """A COM backend with nothing registered/running is dropped from auto chain,
    while ODA (a configured binary fallback) is kept."""
    c = DWGConverter(dwg_auto_backends="haochen_com,autocad_com,oda")
    monkeypatch.setattr(DWGConverter, "_running_process_names", lambda self: set())
    monkeypatch.setattr(DWGConverter, "_registered_prog_ids", lambda self: set())
    _sp = monkeypatch._fixture if hasattr(monkeypatch, "_fixture") else None
    monkeypatch.setattr(DWGConverter, "_service_script_path", _script_path_exists)
    monkeypatch.setattr(DWGConverter, "_candidate_oda_paths", lambda self: iter([Path("/opt/ODAFileConverter.exe")]))
    sel = c._select_auto_backends()
    assert "autocad_com" not in sel
    assert "haochen_com" not in sel
    assert "oda" in sel


def test_sieve_reports_not_installed_reason(monkeypatch):
    c = DWGConverter(dwg_auto_backends="autocad_com")
    monkeypatch.setattr(DWGConverter, "_running_process_names", lambda self: set())
    monkeypatch.setattr(DWGConverter, "_registered_prog_ids", lambda self: set())
    _sp = monkeypatch._fixture if hasattr(monkeypatch, "_fixture") else None
    monkeypatch.setattr(DWGConverter, "_service_script_path", _script_path_exists)
    info = c.inspect_backends()["autocad_com"]
    assert info["detected"] is False
    assert info["reason"] == "not_detected"
    assert "actionable" in info and info["actionable"]

def test_service_synchronous_connect_is_same_thread_and_usable(monkeypatch, win32com_client):
    """Regression: activation must run on the *current* COM thread and the
    returned instance must be usable for Version/Documents immediately after
    connect (no worker thread CoUninitialize'ing then handing a dead proxy back).
    """
    import threading as _threading
    monkeypatch.setattr(disc, "any_autocad_registered", lambda: True)
    monkeypatch.setattr(
        disc, "discovered_autocad_progids", lambda: ["AutoCAD.Application.26"]
    )
    converter = ac_mod.AutoCADConverter()
    dispatch_thread = {}

    class FakeApp:
        def __init__(self):
            self.Visible = True
            self.Version = "25.1s (LMS Tech)"
            self.Documents = object()

        def Quit(self):
            self.Visible = False

    def fake_dispatch(prog_id):
        dispatch_thread["id"] = _threading.get_ident()
        return FakeApp()

    win32com_client.GetActiveObject = lambda prog_id: (_ for _ in ()).throw(RuntimeError("no active"))
    win32com_client.Dispatch = fake_dispatch

    assert converter.connect_to_cad() is True
    # Activation ran on this very thread (same apartment), never a worker.
    assert dispatch_thread["id"] == _threading.get_ident()
    # The proxy is alive and usable for the members a conversion touches.
    assert converter.app is not None
    assert converter.app.Version == "25.1s (LMS Tech)"
    assert converter.app.Documents is not None


def test_service_reports_activation_failure_when_all_dispatch_fail(monkeypatch, win32com_client):
    """A registered-but-unusable backend yields an actionable failure rather
    than blocking; bounded per-attempt activation is delegated to the probe /
    subprocess boundary, so connect simply records why each ProgID failed."""
    monkeypatch.setattr(disc, "any_autocad_registered", lambda: True)
    monkeypatch.setattr(
        disc, "discovered_autocad_progids", lambda: ["AutoCAD.Application.26"]
    )
    converter = ac_mod.AutoCADConverter()

    def fail_dispatch(prog_id):
        raise RuntimeError("CO_E_RUNAS_LOGON_FAILURE")

    win32com_client.GetActiveObject = lambda prog_id: (_ for _ in ()).throw(RuntimeError("no active"))
    win32com_client.Dispatch = fail_dispatch

    assert converter.connect_to_cad() is False
    assert converter.last_error is not None
    assert "activation failed" in converter.last_error.lower()
    assert converter.app is None





# --------------------------- subprocess reclamation ---------------------------

def test_com_subprocess_timeout_reclaims_started_cad(monkeypatch):
    """A COM conversion subprocess that times out must reclaim (kill) any CAD
    process it started, so a late-returning COM server leaves no orphan
    acad.exe / gcad.exe behind.  Only *new* PIDs are killed, never a user's
    already-open CAD."""
    import subprocess as _sp
    import tempfile

    # Prepare a real input dwg + output path so _prepare_com_paths works.
    work = Path(tempfile.mkdtemp(prefix="cad_sieve_"))
    src = work / "in.dwg"
    src.write_bytes(b"dummy")
    out_dir = work / "out"
    out_dir.mkdir(exist_ok=True)
    out_dxf = out_dir / "in.dxf"

    killed = []
    c = DWGConverter(cad_converter_timeout=60)
    monkeypatch.setattr(c, "_kill_pids", lambda pids: killed.extend(sorted(pids)))
    monkeypatch.setattr(c, "_com_attempt_timeout", lambda: 5)
    # Before the subprocess a stale acad.exe PID 1000 exists; after a hung
    # attempt a fresh PID 9999 appears. Only the new PID must be reclaimed.
    seen = {"n": 0}
    def cad_pids_seq(images):
        seen["n"] += 1
        return {"1000"} if seen["n"] == 1 else {"1000", "9999"}
    monkeypatch.setattr(c, "_cad_pids", cad_pids_seq)

    def fake_run(*a, **kw):
        raise _sp.TimeoutExpired(cmd=kw.get("command", []), timeout=5)

    monkeypatch.setattr("subprocess.run", fake_run)

    try:
        c._run_com_converter("app.services.autocad_converter", "AutoCADConverter", str(src), str(out_dxf))
        raise AssertionError("expected a ValueError for timeout")
    except ValueError as exc:
        assert "timed out" in str(exc)
    # Only the new PID (9999) was reclaimed; the pre-existing 1000 was preserved.
    assert killed == ["9999"]


# ---------------------------------------------------------------------------
# Probe-then-connect race regression: a probe that Dispatch'd + Quit a CAD
# leaves a stale ROT entry; an immediate GetActiveObject returns a stale active
# proxy that fails Version/Documents.  The connection layer must validate and
# re-Dispatch a fresh usable instance instead of binding to the dying one.
# ---------------------------------------------------------------------------
def test_connect_after_probe_redispatch_when_active_stale(monkeypatch, win32com_client):
    """A probe quit a Dispatch'd instance; the very next connect's
    GetActiveObject returns that stale proxy (no live Version/Documents).  The
    connection must discard it and Dispatch a fresh usable CAD, then expose a
    working Version/Documents -- never a dead proxy."""
    monkeypatch.setattr(disc, "any_autocad_registered", lambda: True)
    monkeypatch.setattr(
        disc, "discovered_autocad_progids", lambda: ["AutoCAD.Application.26"]
    )
    converter = ac_mod.AutoCADConverter()

    # Probe already ran and Quit a Dispatch'd instance (simulated by the caller
    # of the connection).  ROT still hands it to GetActiveObject: a *stale*
    # proxy whose COM surface is gone -> reading Version/Documents raises.
    class StaleProxy:
        # Emulate a dead COM proxy: any member access raises (server gone).
        def __getattr__(self, _name):
            raise RuntimeError("RPC server unavailable (stale proxy)")

    class FreshApp:
        Visible = True
        Version = "26.0s (LMS Tech)"
        Documents = object()

    calls = {"get_active": 0, "dispatch": 0}
    win32com_client.GetActiveObject = lambda prog_id: (
        calls.__setitem__("get_active", calls["get_active"] + 1) or StaleProxy()
    )
    win32com_client.Dispatch = lambda prog_id: (
        calls.__setitem__("dispatch", calls["dispatch"] + 1) or FreshApp()
    )

    assert converter.connect_to_cad() is True
    # The stale GetActiveObject result was rejected and a fresh Dispatch issued.
    assert calls["dispatch"] == 1
    assert converter._stale_active_retried is True
    # The connected instance is the usable fresh one (never a dead proxy).
    assert converter.app is not None
    assert converter.app.Version == "26.0s (LMS Tech)"
    assert converter.app.Documents is not None


def test_connect_accepts_usable_active_instance(monkeypatch, win32com_client):
    """A genuinely live already-running CAD (GetActiveObject) is still accepted
    -- only stale/unusable proxies are re-dispatched."""
    monkeypatch.setattr(disc, "any_autocad_registered", lambda: True)
    monkeypatch.setattr(
        disc, "discovered_autocad_progids", lambda: ["AutoCAD.Application.26"]
    )
    converter = ac_mod.AutoCADConverter()

    class LiveActiveApp:
        Visible = True
        Version = "25.1s (LMS Tech)"
        Documents = object()

    win32com_client.GetActiveObject = lambda prog_id: LiveActiveApp()
    win32com_client.Dispatch = lambda prog_id: (_ for _ in ()).throw(
        AssertionError("should not Dispatch a live active instance")
    )

    assert converter.connect_to_cad() is True
    assert converter._stale_active_retried is False
    assert converter.app.Version == "25.1s (LMS Tech)"


# ---------------------------------------------------------------------------
# Disconnect cleanup: an instance the connection *started* (Dispatch) is Quit on
# disconnect so no stray acad.exe / ROT entry lingers; a merely-attached
# (GetActiveObject) instance owned by the user is left running.
# ---------------------------------------------------------------------------
def test_disconnect_quits_dispatch_started_instance(monkeypatch, win32com_client):
    monkeypatch.setattr(disc, "any_autocad_registered", lambda: True)
    monkeypatch.setattr(
        disc, "discovered_autocad_progids", lambda: ["AutoCAD.Application.26"]
    )
    converter = ac_mod.AutoCADConverter()
    quit_calls = {"n": 0}

    class FreshApp:
        Visible = True
        Version = "26.0s (LMS Tech)"
        Documents = object()

        def Quit(self):
            quit_calls["n"] += 1
            self.Visible = False

    win32com_client.GetActiveObject = lambda prog_id: (_ for _ in ()).throw(
        RuntimeError("no active")
    )
    win32com_client.Dispatch = lambda prog_id: FreshApp()

    assert converter.connect_to_cad() is True
    assert converter._dispatch_started is True
    converter.disconnect()
    # The Dispatch-started instance was Quit (no residual acad.exe).
    assert quit_calls["n"] == 1
    assert converter.app is None


def test_disconnect_leaves_attached_instance_running(monkeypatch, win32com_client):
    """An attached (GetActiveObject) instance belongs to the user and must not
    be Quit on disconnect -- only visibility is restored."""
    monkeypatch.setattr(disc, "any_autocad_registered", lambda: True)
    monkeypatch.setattr(
        disc, "discovered_autocad_progids", lambda: ["AutoCAD.Application.26"]
    )
    converter = ac_mod.AutoCADConverter()
    quit_calls = {"n": 0}

    class LiveApp:
        Visible = False
        Version = "25.1s (LMS Tech)"
        Documents = object()

        def Quit(self):
            quit_calls["n"] += 1

    win32com_client.GetActiveObject = lambda prog_id: LiveApp()
    win32com_client.Dispatch = lambda prog_id: (_ for _ in ()).throw(
        AssertionError("should not Dispatch")
    )

    assert converter.connect_to_cad() is True
    assert converter._dispatch_started is False
    converter.disconnect()
    # No Quit issued; visibility restored (it was hidden for background mode).
    assert quit_calls["n"] == 0
    assert converter.app is None

# ---------------------------------------------------------------------------
# Probe timeout reclamation: a hung COM server (registered-but-never-answers
# 浩辰/中望) can start a CAD process (e.g. gcad.exe) before Dispatch stalls.
# _probe_com_activation must reclaim only the *newly-started* matching CAD PID
# it observed (never a user's already-open CAD) when a per-ProgID probe outcome
# reports cleanup_required=True.
# ---------------------------------------------------------------------------
def _make_probe_outcome(reason, cleanup_required, prog_id):
    return {
        "reason": reason,
        "prog_id": prog_id,
        "detail": "probe outcome",
        "closed": False,
        "cleanup_required": cleanup_required,
        "quit_confirmed": False,
    }


def test_probe_timeout_reclaims_only_newly_started_cad(monkeypatch):
    """Regression: a timeout reporting cleanup_required (hung COM server started
    a gcad.exe that never answered Dispatch) must have that stray process
    reclaimed, leaving a pre-existing user CAD untouched."""
    c = DWGConverter(dwg_auto_backends="autocad_com")
    monkeypatch.setattr(disc, "discovered_autocad_progids", lambda: ["AutoCAD.Application.26"])
    killed = []

    monkeypatch.setattr(c, "_kill_pids", lambda pids: killed.extend(sorted(pids)))
    # Before probing a stale gcad.exe (PID 1000) already runs (a user's open CAD);
    # after the timeout a fresh gcad.exe PID 9999 appeared (started by the hung
    # probe).  Only 9999 must be reclaimed, never the pre-existing 1000.
    seen = {"n": 0}

    def cad_pids_seq(images):
        seen["n"] += 1
        return {"1000"} if seen["n"] == 1 else {"1000", "9999"}

    monkeypatch.setattr(c, "_cad_pids", cad_pids_seq)

    outcome = _make_probe_outcome(cp_mod.ACTIVATION_TIMEOUT, True, "AutoCAD.Application.26")

    def fake_probe(prog_ids, timeout):
        return cp_mod.ACTIVATION_TIMEOUT, [outcome]

    monkeypatch.setattr(cp_mod, "probe_registered_prog_ids", fake_probe)

    reason = c._probe_com_activation("autocad_com")
    assert reason == "activation_timeout"
    # Only the newly started PID (9999) was reclaimed; the pre-existing 1000
    # (a user's CAD) was left alone.
    assert killed == ["9999"]


def test_probe_timeout_without_new_cad_kills_nothing(monkeypatch):
    """Regression: when a probe times out with cleanup_required=True but no new
    CAD process appeared (the COM server never actually started one), nothing is
    killed -- only the pre-existing user CAD remains, so no spurious kill."""
    c = DWGConverter(dwg_auto_backends="haochen_com")
    killed = []
    monkeypatch.setattr(c, "_kill_pids", lambda pids: killed.extend(sorted(pids)))
    # No CAD process appears before or after (host idle apart from a user gcad
    # PID 1000 that predates and outlives the probe).
    monkeypatch.setattr(c, "_cad_pids", lambda images: {"1000"})
    monkeypatch.setattr(disc, "discovered_autocad_progids", lambda: [])

    outcome = _make_probe_outcome(cp_mod.ACTIVATION_TIMEOUT, True, "GStarCAD.Application.26")

    def fake_probe(prog_ids, timeout):
        return cp_mod.ACTIVATION_TIMEOUT, [outcome]

    monkeypatch.setattr(cp_mod, "probe_registered_prog_ids", fake_probe)

    reason = c._probe_com_activation("haochen_com")
    assert reason == "activation_timeout"
    # after - before is empty -> no process to reclaim.
    assert killed == []


def test_probe_activatable_no_cleanup_no_reclaim(monkeypatch):
    """When the probe succeeds (activatable), no outcome carries
    cleanup_required, so no CAD PID is reclaimed -- a healthy install is left
    entirely alone."""
    c = DWGConverter(dwg_auto_backends="autocad_com")
    killed = []
    monkeypatch.setattr(c, "_kill_pids", lambda pids: killed.extend(sorted(pids)))
    monkeypatch.setattr(c, "_cad_pids", lambda images: set())  # idle host
    monkeypatch.setattr(disc, "discovered_autocad_progids", lambda: ["AutoCAD.Application.26"])

    ok_outcome = _make_probe_outcome(cp_mod.ACTIVATABLE, False, "AutoCAD.Application.26")

    def fake_probe(prog_ids, timeout):
        return cp_mod.ACTIVATABLE, [ok_outcome]

    monkeypatch.setattr(cp_mod, "probe_registered_prog_ids", fake_probe)

    reason = c._probe_com_activation("autocad_com")
    assert reason == "activatable"
    assert killed == []

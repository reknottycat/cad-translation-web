#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the bounded COM activation probe (no real CAD COM needed).

Simulates a Windows host by faking ``_is_windows`` and providing a fake
``pythoncom`` / ``win32com.client`` so ``Dispatch``/``GetActiveObject`` can be
made to succeed, raise, or hang -- verifying the per-attempt timeout actually
bounds a slow COM server.
"""

from __future__ import annotations

import sys
import threading
import types
import time

import pytest

from app.functions import com_activation_probe as probe


class _FakePythoncom:
    def CoInitialize(self):
        return 0

    def CoUninitialize(self):
        return None


class _FakeClient:
    def __init__(self, get_active=None, dispatch=None):
        self._get_active = get_active
        self._dispatch = dispatch

    def GetActiveObject(self, prog_id):
        if self._get_active is None:
            raise RuntimeError("no active object")
        return self._get_active(prog_id)

    def Dispatch(self, prog_id):
        if self._dispatch is None:
            raise RuntimeError("dispatch failed")
        return self._dispatch(prog_id)


@pytest.fixture
def fake_com(monkeypatch):
    """Install a fake pythoncom + client and pretend we are on Windows."""
    monkeypatch.setattr(probe, "_is_windows", lambda: True)
    fake = {}
    monkeypatch.setattr(probe, "_import_com", lambda: (_FakePythoncom(), fake["client"]))
    return fake


def test_off_windows_returns_not_installed(monkeypatch):
    monkeypatch.setattr(probe, "_is_windows", lambda: False)
    r = probe.activate_prog_id_with_timeout("X.Application", 0.2)
    assert r["reason"] == probe.NOT_INSTALLED


def test_dispatch_success_classifies_activatable(fake_com):
    fake_com["client"] = _FakeClient(dispatch=lambda pid: types.SimpleNamespace())
    r = probe.activate_prog_id_with_timeout("GStarCAD.Application.26", 2)
    assert r["reason"] == probe.ACTIVATABLE
    assert r["closed"] is True


def test_active_object_success(fake_com):
    fake_com["client"] = _FakeClient(
        get_active=lambda pid: types.SimpleNamespace(),
        dispatch=lambda pid: (_ for _ in ()).throw(RuntimeError("should not dispatch")),
    )
    r = probe.activate_prog_id_with_timeout("AutoCAD.Application.25", 2)
    assert r["reason"] == probe.ACTIVATABLE


def test_dispatch_failure_classifies_activation_failed(fake_com):
    fake_com["client"] = _FakeClient(
        get_active=lambda pid: (_ for _ in ()).throw(RuntimeError("no active")),
        dispatch=lambda pid: (_ for _ in ()).throw(RuntimeError("COM_E 0x80040154")),
    )
    r = probe.activate_prog_id_with_timeout("GStarCAD.Application", 2)
    assert r["reason"] == probe.ACTIVATION_FAILED
    assert "COM_E" in r["detail"]


def test_hanging_dispatch_is_bounded_and_reports_timeout(fake_com):
    def hang(pid):
        time.sleep(5)
        return types.SimpleNamespace()

    fake_com["client"] = _FakeClient(
        get_active=lambda pid: (_ for _ in ()).throw(RuntimeError("no active")),
        dispatch=hang,
    )
    start = time.monotonic()
    r = probe.activate_prog_id_with_timeout("GStarCAD.Application", 0.3)
    elapsed = time.monotonic() - start
    assert r["reason"] == probe.ACTIVATION_TIMEOUT
    assert elapsed < 3, f"activation not bounded, took {elapsed:.2f}s"
    assert "0.3" in r["detail"] or "did not complete" in r["detail"]


def test_probe_multiple_hits_first_activatable(fake_com):
    fake_com["client"] = _FakeClient(
        get_active=lambda pid: (_ for _ in ()).throw(RuntimeError("no active")),
        dispatch=lambda pid: types.SimpleNamespace()
        if pid == "AutoCAD.Application.26"
        else (_ for _ in ()).throw(RuntimeError("bad")),
    )
    reason, per = probe.probe_registered_prog_ids(
        ["GStarCAD.Application", "AutoCAD.Application.26"], 2
    )
    assert reason == probe.ACTIVATABLE
    assert per[0]["reason"] == probe.ACTIVATION_FAILED  # first one failed


def test_probe_all_timeouts_gives_timeout(fake_com):
    def hang(pid):
        time.sleep(5)
    fake_com["client"] = _FakeClient(
        get_active=lambda pid: (_ for _ in ()).throw(RuntimeError("no active")),
        dispatch=hang,
    )
    reason, per = probe.probe_registered_prog_ids(["A.App", "B.App"], 0.3)
    assert reason == probe.ACTIVATION_TIMEOUT


# ---------------------------------------------------------------------------
# Real-import regression (no monkeypatching of _import_com).
#
# pywin32 is Windows-only and absent in CI, so we register stub *modules* in
# sys.modules and let _import_com() run its genuine `import` statements. This
# verifies the real import path actually binds win32com.client (a past bug
# returned the never-assigned variable, making every live activation report
# "pywin32 not installed").
# ---------------------------------------------------------------------------
def test_import_com_returns_real_modules_when_available(monkeypatch):
    import importlib

    # Make pythoncom / win32com.client importable WITHOUT patching _import_com.
    # _import_com() runs its genuine `import` statements against sys.modules, so
    # this exercises the real import path (and would have caught the bug that
    # returned the never-assigned win32com_client variable).
    pythoncom_mod = types.ModuleType("pythoncom")
    pythoncom_mod.CoInitialize = lambda: 0
    pythoncom_mod.CoUninitialize = lambda: None

    client_mod = types.ModuleType("win32com.client")
    client_mod.Dispatch = lambda pid: None
    client_mod.GetActiveObject = lambda pid: None

    win32com_pkg = types.ModuleType("win32com")
    win32com_pkg.client = client_mod
    client_mod.__package__ = "win32com"
    win32com_pkg.__path__ = []  # namespace marker so client imports under it

    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom_mod)
    monkeypatch.setitem(sys.modules, "win32com", win32com_pkg)
    monkeypatch.setitem(sys.modules, "win32com.client", client_mod)
    importlib.invalidate_caches()

    pc, wc = probe._import_com()
    # The real import must bind win32com.client (not None), and pythoncom too.
    assert wc is not None, "_import_com returned None for win32com.client"
    assert wc is client_mod
    assert pc is pythoncom_mod


def test_import_com_returns_none_when_absent(monkeypatch):
    # With no pywin32 modules importable, the genuine import path returns
    # (None, None) so callers can report SCRIPT_MISSING on non-Windows hosts.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name.startswith("pythoncom") or name.startswith("win32com"):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    pc, wc = probe._import_com()
    assert pc is None and wc is None


# ---------------------------------------------------------------------------
# COM apartment regression: a probed instance must never be handed to the
# caller thread; it is closed inside the worker's own apartment.
# ---------------------------------------------------------------------------
def test_probe_never_returns_live_instance_and_closes_on_worker(fake_com, monkeypatch):
    closed_in_worker = {}

    class _VersionedApp:
        Version = "25.1s (LMS Tech)"
        Documents = object()

        def Quit(self):
            closed_in_worker["quit"] = True

    fake_com["client"] = _FakeClient(
        get_active=lambda pid: (_ for _ in ()).throw(RuntimeError("no active")),
        dispatch=lambda pid: _VersionedApp(),
    )
    # Replace the real close with a probe we can observe, running on the worker.
    orig_close = probe._close_instance

    def spy_close(instance):
        orig_close(instance)
        closed_in_worker["closed"] = True

    monkeypatch.setattr(probe, "_close_instance", spy_close)

    r = probe.activate_prog_id_with_timeout("AutoCAD.Application.25.1", 2)
    assert r["reason"] == probe.ACTIVATABLE
    # Classification result carries no live COM instance across threads.
    assert "instance" not in r
    # The instance was closed (Quit) inside the worker's own apartment.
    assert closed_in_worker.get("closed") is True
    assert closed_in_worker.get("quit") is True


# ---------------------------------------------------------------------------
# ROT/process-residue regression: a probe that Dispatch'd (started) a CAD and
# Quit it must wait for it to leave the Running Object Table so an immediate
# connection cannot bind to a stale active proxy.  _confirm_quit_drained polls
# GetActiveObject until the quit instance is deregistered (no running object).
# ---------------------------------------------------------------------------
def test_probe_confirms_launched_instance_leaves_rot_after_quit(fake_com, monkeypatch):
    class _QuitTrackingApp:
        Version = "26.0s"
        Documents = object()

        def Quit(self):
            pass

    # Call sequence for GetActiveObject:
    #   1) activation: no active object yet -> the probe falls through to
    #      Dispatch and starts (and later Quits) a fresh instance;
    #   2) post-Quit confirmation poll: still reachable for one poll (ROT not yet
    #      drained), then raises -> the quit instance has deregistered.
    active_calls = {"n": 0}

    class _StaleThenGone:
        def Quit(self):
            pass

    stale = _StaleThenGone()

    def fake_get_active(prog_id):
        active_calls["n"] += 1
        if active_calls["n"] == 1:
            raise RuntimeError("no running object")  # -> force Dispatch
        if active_calls["n"] == 2:
            return stale  # just quit, still reachable for one poll
        raise RuntimeError("no running object")  # deregistered

    fake_com["client"] = _FakeClient(
        get_active=fake_get_active,
        dispatch=lambda pid: _QuitTrackingApp(),
    )

    r = probe.activate_prog_id_with_timeout("AutoCAD.Application.26", 2)
    assert r["reason"] == probe.ACTIVATABLE
    assert r["closed"] is True
    # The probe polled until the quit instance left the ROT (best effort).
    assert r["quit_confirmed"] is True


def test_probe_quit_confirm_never_blocks_past_cap(fake_com, monkeypatch):
    """If the quit CAD never fully deregisters, the bounded confirm returns
    False (does not hang), leaving the connection layer's stale-proxy handling
    to re-Dispatch safely."""
    import time as _time

    class _QuitTrackingApp:
        Version = "26.0s"
        Documents = object()

        def Quit(self):
            pass

    # Activation has no active object (forces Dispatch); the post-Quit
    # confirmation poll always sees an instance (the CAD never deregisters), so
    # _confirm_quit_drained must stop at its own cap instead of hanging.
    active_calls = {"n": 0}

    def fake_get_active(prog_id):
        active_calls["n"] += 1
        if active_calls["n"] == 1:
            raise RuntimeError("no running object")  # -> force Dispatch
        return _QuitTrackingApp()  # never drains during confirm polls

    fake_com["client"] = _FakeClient(
        get_active=fake_get_active,
        dispatch=lambda pid: _QuitTrackingApp(),
    )
    # Tiny cap so the test does not actually wait 8s.
    monkeypatch.setattr(probe, "DEFAULT_QUIT_CONFIRM_TIMEOUT", 0.3)
    start = _time.monotonic()
    r = probe.activate_prog_id_with_timeout("AutoCAD.Application.26", 2)
    elapsed = _time.monotonic() - start
    assert r["reason"] == probe.ACTIVATABLE
    assert r["quit_confirmed"] is False
    assert elapsed < 3, f"quit confirm overran bound: {elapsed:.2f}s"

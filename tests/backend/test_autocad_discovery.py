#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for AutoCAD COM discovery & diagnostics (no real AutoCAD needed).

Mocks ``winreg``, the process table and the bridge-script presence so the
probe can be exercised on any host (including CI / non-Windows).  The registry
logic is platform-independent once the module-level ``winreg`` handle is faked,
so we never need to mutate the global ``os.name``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.functions import autocad_discovery as disc


class _Hive:
    """A fake registry hive that enumerates child keys from a fixed list."""

    def __init__(self, children):
        self._children = list(children)

    def __iter__(self):
        return iter(self._children)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeWinreg:
    HKEY_LOCAL_MACHINE = 1
    HKEY_CURRENT_USER = 2
    HKEY_CLASSES_ROOT = 3
    KEY_READ = 0x20019
    KEY_WOW64_64KEY = 0x0100
    KEY_WOW64_32KEY = 0x0200

    def __init__(self, machine=None, user=None):
        self._machine = list(machine or [])
        self._user = list(user or [])
        self.open_class_root = []

    def OpenKey(self, key, subkey, *rest, **kwargs):
        if subkey == r"Software\Classes":
            if key == self.HKEY_LOCAL_MACHINE:
                return _Hive(self._machine)
            if key == self.HKEY_CURRENT_USER:
                return _Hive(self._user)
        if key == self.HKEY_CLASSES_ROOT:
            self.open_class_root.append(subkey)
        return _Hive([])

    def EnumKey(self, hive, index):
        children = list(hive)
        if index >= len(children):
            raise OSError("no more keys")
        return children[index]


@pytest.fixture
def fake_winreg(monkeypatch):
    fake = _FakeWinreg()
    monkeypatch.setattr(disc, "winreg", fake)
    monkeypatch.setattr(disc, "_is_windows", lambda: True)
    return fake


def _install(machine, user=None, monkeypatch=None):
    fake = _FakeWinreg(machine=machine, user=user)
    monkeypatch.setattr(disc, "winreg", fake)
    monkeypatch.setattr(disc, "_is_windows", lambda: True)
    return fake


def test_supports_future_versions_beyond_2022(monkeypatch):
    """Versioned ProgIDs newer than the static baseline are recognised."""
    machine = [
        "AutoCAD.Application",
        "AutoCAD.Application.26.1",
        "AutoCAD.Application.26",
        "AutoCAD.Application.25",
    ]
    _install(machine=machine, monkeypatch=monkeypatch)
    prog_ids = disc.discovered_autocad_progids()
    low = [p.lower() for p in prog_ids]
    assert "autocad.application.26.1" in low
    assert "autocad.application.26" in low
    assert "autocad.application" in low
    # Versioned ones sort newest first.
    i26 = low.index("autocad.application.26.1")
    i25 = low.index("autocad.application.25")
    assert i26 < i25


def test_discovery_on_non_windows_returns_empty_without_winreg(monkeypatch):
    """Without winreg (non-Windows) nothing is enumerated and no exception."""
    monkeypatch.setattr(disc, "winreg", None)
    assert disc.discovered_autocad_progids() == []
    assert disc.any_autocad_registered() is False


def test_any_autocad_registered_true(monkeypatch):
    _install(machine=["AutoCAD.Application.25"], monkeypatch=monkeypatch)
    assert disc.any_autocad_registered() is True


def test_probe_not_installed(monkeypatch):
    """No registration and no running process -> not_installed with actionable msg."""
    _install(machine=[], monkeypatch=monkeypatch)
    res = disc.probe_autocad_presence(bridge_script_present=True, registered=False, running=False)
    assert res["reason"] == disc.NOT_INSTALLED
    assert "install" in res["actionable"].lower() or "No AutoCAD" in res["actionable"]


def test_probe_registered_but_not_running(monkeypatch):
    _install(machine=["AutoCAD.Application.25"], monkeypatch=monkeypatch)
    res = disc.probe_autocad_presence(bridge_script_present=True, registered=True, running=False)
    assert res["reason"] == disc.REGISTERED


def test_probe_process_running(monkeypatch):
    _install(machine=[], monkeypatch=monkeypatch)
    res = disc.probe_autocad_presence(bridge_script_present=True, registered=False, running=True)
    assert res["reason"] == disc.PROCESS_RUNNING


def test_probe_script_missing(monkeypatch):
    """A missing Python bridge script must never be treated as installed."""
    _install(machine=["AutoCAD.Application.25"], monkeypatch=monkeypatch)
    res = disc.probe_autocad_presence(bridge_script_present=False, registered=True, running=False)
    assert res["reason"] == disc.SCRIPT_MISSING
    assert res["any_registered"] is False  # script missing dominates detection


def test_probe_actionable_for_registered(monkeypatch):
    _install(machine=["AutoCAD.Application.25"], monkeypatch=monkeypatch)
    res = disc.probe_autocad_presence(bridge_script_present=True, registered=True, running=False)
    assert "registered" in res["actionable"].lower()


def test_tasklist_process_noop_off_windows(monkeypatch):
    """Off-Windows the process probe short-circuits to False without subprocess."""
    monkeypatch.setattr(disc, "_is_windows", lambda: False)
    assert disc._running_autocad_process() is False


def test_probe_defaults_live_when_not_overridden(monkeypatch, fake_winreg):
    """When overrides are omitted the probe still returns a consistent dict."""
    res = disc.probe_autocad_presence(bridge_script_present=True)
    assert res["reason"] in {disc.REGISTERED, disc.PROCESS_RUNNING, disc.NOT_INSTALLED}

def test_discovered_progids_no_case_duplicates(monkeypatch):
    """Registered CamelCase entries plus the lower-case baseline must not yield
    duplicate ProgIDs differing only by case."""
    machine = [
        "AutoCAD.Application",
        "AutoCAD.Application.25.1",
        "AutoCAD.Application.25",
        "AutoCAD.Application.24",
    ]
    _install(machine=machine, monkeypatch=monkeypatch)
    prog_ids = disc.discovered_autocad_progids()
    lower = [p.lower() for p in prog_ids]
    assert len(lower) == len(set(lower)), f"duplicate case-insensitive entries: {prog_ids}"
    # The registered 25.1 / 25 appear exactly once.
    assert lower.count("autocad.application.25.1") == 1
    assert lower.count("autocad.application.25") == 1
    # .24 (CamelCase from registry) appears exactly once; the lower-case baseline
    # entry must NOT be appended as a duplicate of it.
    assert lower.count("autocad.application.24") == 1

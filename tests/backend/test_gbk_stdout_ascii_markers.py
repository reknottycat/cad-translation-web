#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for COM subprocess/service stdout under a GBK console.

On Windows the console code page is often GBK (cp936) and ``PYTHONIOENCODING``
is not set, so CPython writes to stdout through a strict GBK stream.  The COM
converter service layer prints machine-facing progress/diagnostic markers; if
any such marker were a Unicode symbol such as ``✓`` / ``✗`` (U+2713 / U+2717),
a plain ``print()`` would raise ``UnicodeEncodeError`` and the whole conversion
would die before it could disconnect -- even though the COM operation itself
succeeded.

These tests guard against regressions:

* the service modules must not contain *any* character that strict GBK cannot
  encode (so no output path can crash a GBK stdout);
* the connect success / failure paths use ASCII-stable ``[OK]`` / ``[ERROR]``
  markers instead of ``✓`` / ``✗``;
* running the real connect path under a GBK-encoding stream succeeds and every
  emitted line round-trips through strict GBK (no ``UnicodeEncodeError``).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ---------------------------------------------------------------------------
# Stub win32com so the service modules can be imported on a non-Windows host.
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

from app.services import autocad_converter as ac_mod  # noqa: E402
from app.services import haochen_optimized_converter as hc_mod  # noqa: E402
from app.functions import autocad_discovery as disc  # noqa: E402


def _assert_gbk_safe(text: str, where: str) -> None:
    """Assert ``text`` can be encoded with strict GBK (the Windows console
    default when ``PYTHONIOENCODING`` is unset).  Any non-GBK character would
    have raised ``UnicodeEncodeError`` on a real GBK stdout."""
    try:
        text.encode("gbk", "strict")
    except UnicodeEncodeError as exc:  # pragma: no cover - shows the bug
        ch = text[exc.start]
        pytest.fail(
            f"{where} produced non-GBK character U+{ord(ch):04X} ({ch!r}) "
            f"that would raise UnicodeEncodeError under a GBK stdout; use an "
            f"ASCII marker such as [OK]/[ERROR]."
        )


# ---------------------------------------------------------------------------
# 1. Source-level: no non-GBK-encodable character may remain in the modules.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "rel_path",
    [
        "backend/app/services/autocad_converter.py",
        "backend/app/services/haochen_optimized_converter.py",
    ],
)
def test_service_modules_contain_only_gbk_encodable_chars(rel_path):
    repo_root = Path(__file__).resolve().parents[2]
    text = (repo_root / rel_path).read_text(encoding="utf-8")
    _assert_gbk_safe(text, rel_path)


def test_connect_print_strings_use_ascii_markers_not_unicode_symbols():
    repo_root = Path(__file__).resolve().parents[2]
    for rel in (
        "backend/app/services/autocad_converter.py",
        "backend/app/services/haochen_optimized_converter.py",
    ):
        src = (repo_root / rel).read_text(encoding="utf-8")
        assert "\u2713" not in src, f"{rel} must use [OK], not U+2713 '✓'"
        assert "\u2717" not in src, f"{rel} must use [ERROR], not U+2717 '✗'"


# ---------------------------------------------------------------------------
# 2. Functional: running the real connect path under GBK stdout must succeed
#    (no UnicodeEncodeError) and every emitted line must round-trip through
#    strict GBK.  Because Python's builtin ``print`` writes whatever the caller
#    passes to stdout, a GBK console only ever fails when a non-GBK character
#    is present in the emitted text; asserting GBK-safety of the captured
#    output is therefore equivalent to "no UnicodeEncodeError on a GBK stdout".
# ---------------------------------------------------------------------------
@pytest.fixture
def win32com_client(monkeypatch):
    client = sys.modules["win32com.client"]
    client.GetActiveObject = lambda prog_id: (_ for _ in ()).throw(
        RuntimeError("no active")
    )
    client.Dispatch = lambda prog_id: (_ for _ in ()).throw(
        RuntimeError("activation failed")
    )
    return client


@pytest.mark.parametrize(
    "make_converter",
    [
        lambda: ac_mod.AutoCADConverter(),
        lambda: hc_mod.OptimizedHaoChenCADConverter(),
    ],
    ids=["autocad_converter", "haochen_converter"],
)
def test_connect_success_output_is_gbk_safe(
    monkeypatch, win32com_client, capsys, make_converter
):
    """The connect-success output path emits a readable, ASCII-marked
    diagnostic and every printed character is strict-GBK encodable (so a GBK
    console / unset PYTHONIOENCODING will not raise UnicodeEncodeError)."""
    monkeypatch.setattr(disc, "any_autocad_registered", lambda: True)
    monkeypatch.setattr(
        disc, "discovered_autocad_progids", lambda: ["AutoCAD.Application.26"]
    )

    converter = make_converter()

    class FakeApp:
        Visible = True
        Version = "26.0s (LMS Tech)"
        Documents = object()

    win32com_client.GetActiveObject = lambda prog_id: (_ for _ in ()).throw(
        RuntimeError("no active")
    )
    win32com_client.Dispatch = lambda prog_id: FakeApp()

    # Must complete without UnicodeEncodeError (connect success path).
    assert converter.connect_to_cad() is True
    assert converter.connected is True

    out = capsys.readouterr().out
    # Readable diagnosis was emitted, with an ASCII-stable success marker.
    assert "[OK]" in out
    assert "\u2713" not in out and "\u2717" not in out
    # Every emitted line must survive a strict GBK stream.
    _assert_gbk_safe(out, "connect_to_cad success output")


def test_connect_failure_output_is_gbk_safe(monkeypatch, win32com_client, capsys):
    """The failure diagnostic path (all ProgIDs fail) must also be GBK-safe and
    use an ASCII [ERROR] marker."""
    monkeypatch.setattr(disc, "any_autocad_registered", lambda: True)
    monkeypatch.setattr(
        disc, "discovered_autocad_progids", lambda: ["AutoCAD.Application.26"]
    )
    converter = ac_mod.AutoCADConverter()

    def fail_dispatch(prog_id):
        raise RuntimeError("activation failed")

    win32com_client.GetActiveObject = lambda prog_id: (_ for _ in ()).throw(
        RuntimeError("no active")
    )
    win32com_client.Dispatch = fail_dispatch

    assert converter.connect_to_cad() is False
    out = capsys.readouterr().out
    assert "[ERROR]" in out
    assert "\u2713" not in out and "\u2717" not in out
    _assert_gbk_safe(out, "connect_to_cad failure output")

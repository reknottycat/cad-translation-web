from __future__ import annotations

import sys
from pathlib import Path

import pytest

from cli_anything.cad.utils import backend_bridge


def test_backend_bridge_uses_explicit_backend_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backend_dir = tmp_path / "backend"
    (backend_dir / "app").mkdir(parents=True)
    monkeypatch.setenv("CAD_TRANSLATION_BACKEND_DIR", str(backend_dir))
    monkeypatch.setattr(sys, "path", [entry for entry in sys.path if entry != str(backend_dir)])

    resolved = backend_bridge.ensure_backend_path()

    assert resolved == backend_dir
    assert str(backend_dir) == sys.path[0]


def test_backend_bridge_fails_clearly_when_no_backend_can_be_found(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("CAD_TRANSLATION_BACKEND_DIR", raising=False)
    monkeypatch.setattr(backend_bridge, "_repo_root", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RuntimeError, match="CAD_TRANSLATION_BACKEND_DIR"):
        backend_bridge.ensure_backend_path()

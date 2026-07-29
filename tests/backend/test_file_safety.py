from __future__ import annotations

from pathlib import Path
import sys

import pytest


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.utils.file_utils import get_safe_filename, resolve_within_directory


def test_get_safe_filename_strips_path_segments_and_traversal() -> None:
    assert get_safe_filename("../evil.xlsx") == "evil.xlsx"
    assert get_safe_filename(r"..\nested\evil.xlsx") == "evil.xlsx"


def test_resolve_within_directory_rejects_escape_attempts(tmp_path: Path) -> None:
    base_dir = tmp_path / "outputs"
    base_dir.mkdir()

    with pytest.raises(ValueError, match="outside the allowed directory"):
        resolve_within_directory(base_dir, "..\\Windows\\win.ini")


def test_resolve_within_directory_allows_normal_relative_paths(tmp_path: Path) -> None:
    base_dir = tmp_path / "outputs"
    base_dir.mkdir()

    resolved = resolve_within_directory(base_dir, "reports\\translated.xlsx")

    assert resolved == base_dir / "reports" / "translated.xlsx"

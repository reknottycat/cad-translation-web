#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the file locking and atomic write utilities."""

import json
import os
import tempfile
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def test_atomic_write_json_creates_valid_file(temp_dir):
    """Test atomic_write_json produces a valid JSON file."""
    from app.utils.locking import atomic_write_json

    target = temp_dir / "data.json"
    payload = {"key": "value", "nested": {"a": 1, "b": [1, 2, 3]}}

    atomic_write_json(target, payload)

    assert target.exists()
    result = json.loads(target.read_text(encoding="utf-8"))
    assert result == payload


def test_atomic_write_json_replaces_existing(temp_dir):
    """Test atomic_write_json replaces an existing file."""
    from app.utils.locking import atomic_write_json

    target = temp_dir / "data.json"
    atomic_write_json(target, {"old": "data"})
    atomic_write_json(target, {"new": "data"})

    result = json.loads(target.read_text(encoding="utf-8"))
    assert result == {"new": "data"}


def test_atomic_write_json_no_temp_leftovers(temp_dir):
    """Test no temp files are left behind after atomic write."""
    from app.utils.locking import atomic_write_json

    target = temp_dir / "data.json"
    atomic_write_json(target, {"a": 1})

    # No temp files should remain
    temp_files = list(temp_dir.glob("*.tmp"))
    assert len(temp_files) == 0


def test_file_lock_serializes_concurrent_writes(temp_dir):
    """Test that concurrent file-locked writes don't corrupt the file."""
    from app.utils.locking import atomic_write_json, file_lock

    target = temp_dir / "data.json"

    def _write(i: int):
        with file_lock(target):
            # Read current content, then write incrementally
            current = {}
            if target.exists():
                try:
                    current = json.loads(target.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    current = {}
            current[f"key_{i}"] = i
            atomic_write_json(target, current)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(_write, i) for i in range(20)]
        for f in futures:
            f.result(timeout=10)

    # File should be valid JSON with all keys
    result = json.loads(target.read_text(encoding="utf-8"))
    assert len(result) == 20
    for i in range(20):
        assert result[f"key_{i}"] == i


def test_atomic_write_text(temp_dir):
    """Test atomic_write_text creates a file correctly."""
    from app.utils.locking import atomic_write_text

    target = temp_dir / "text.txt"
    atomic_write_text(target, "Hello World")

    assert target.read_text(encoding="utf-8") == "Hello World"


def test_file_lock_is_reentrant(temp_dir):
    """Test that file_lock can be re-acquired within the same thread (RLock)."""
    from app.utils.locking import file_lock

    target = temp_dir / "lockfile"

    with file_lock(target):
        # Re-acquire within the same thread should work (RLock)
        with file_lock(target):
            target.write_text("nested write", encoding="utf-8")

    assert target.read_text(encoding="utf-8") == "nested write"


def test_concurrent_checkpoint_save_load(temp_dir):
    """Test concurrent checkpoint writes don't produce partial reads."""
    from app.utils.locking import atomic_write_json, file_lock
    from concurrent.futures import ThreadPoolExecutor

    checkpoint_path = temp_dir / "checkpoint.json"
    errors = []

    def _writer(i: int):
        try:
            data = [{"id": i, "value": f"v{j}"} for j in range(100)]
            with file_lock(checkpoint_path):
                atomic_write_json(checkpoint_path, data)
        except Exception as exc:
            errors.append(("writer", i, str(exc)))

    def _reader(i: int):
        try:
            if checkpoint_path.exists():
                with file_lock(checkpoint_path):
                    data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                    # Data should always be a valid list
                    assert isinstance(data, list)
        except Exception as exc:
            errors.append(("reader", i, str(exc)))

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for i in range(10):
            futures.append(executor.submit(_writer, i))
            futures.append(executor.submit(_reader, i))
        for f in futures:
            f.result(timeout=10)

    assert not errors, f"Errors: {errors}"


def test_file_lock_uses_sidecar_not_target(temp_dir):
    """file_lock locks a .lock sidecar file, NOT the target data file."""
    from app.utils.locking import atomic_write_json, file_lock

    target = temp_dir / "data.json"

    with file_lock(target):
        # Inside the lock, the sidecar should exist but target should NOT
        # be created by the lock itself
        lock_file = Path(str(target) + ".lock")
        assert lock_file.exists()

    # After the lock context exits, sidecar may still exist
    lock_file = Path(str(target) + ".lock")
    if lock_file.exists():
        # It should be a valid empty file
        assert lock_file.stat().st_size == 0 or lock_file.read_text() == ""


def test_file_lock_preserves_identity_across_atomic_replace(temp_dir):
    """Lock identity must not change when target is atomically replaced.

    This is the critical fix: the lock is on a sidecar .lock file, not on
    the target file that gets replaced by os.replace inside the critical section.
    """
    import os as _os
    from app.utils.locking import atomic_write_json, file_lock

    target = temp_dir / "data.json"

    # Pre-create sidecar and record its inode
    lock_file = Path(str(target) + ".lock")
    lock_file.touch()
    initial_ino = lock_file.stat().st_ino

    # Atomic replace the target inside the lock
    with file_lock(target):
        atomic_write_json(target, {"data": "v1"})

    # The lock sidecar must still exist with the same inode
    assert lock_file.exists()
    assert lock_file.stat().st_ino == initial_ino

    # Target was successfully written
    result = json.loads(target.read_text(encoding="utf-8"))
    assert result == {"data": "v1"}


def test_file_lock_create_parents_false_does_not_mkdir(temp_dir):
    """``file_lock(create_parents=False)`` must NOT create a missing parent
    directory — it raises ``FileNotFoundError`` instead.  This prevents a
    writer from re-creating a task directory that was concurrently deleted."""
    from app.utils.locking import atomic_write_json, file_lock

    # Simulate a deleted task dir: nested path that does not exist.
    nested = temp_dir / "missing_parent" / "task.json"
    assert not nested.parent.exists()

    # file_lock with default create_parents=True WOULD create the parent.
    with file_lock(nested):
        assert nested.parent.exists(), "create_parents=True should mkdir the parent"
    assert nested.parent.exists()

    # Now test create_parents=False on a NEW missing parent.
    nested2 = temp_dir / "another_missing" / "task.json"
    assert not nested2.parent.exists()
    try:
        with file_lock(nested2, create_parents=False):
            raise AssertionError("file_lock(create_parents=False) should have raised")
    except FileNotFoundError:
        pass
    assert not nested2.parent.exists(), (
        "file_lock(create_parents=False) must NOT create the parent directory"
    )

    # atomic_write_json with create_parents=False should silently skip.
    nested3 = temp_dir / "skip_missing" / "checkpoint.json"
    atomic_write_json(nested3, {"data": 1}, create_parents=False)
    assert not nested3.parent.exists(), (
        "atomic_write_json(create_parents=False) must NOT create the parent"
    )


# ---------------------------------------------------------------------------
# Windows atomic-replace regression (Issue #14 / gstack release gate).
#
# On Windows ``os.replace`` can transiently fail with ``PermissionError``
# (WinError 5) when a concurrent reader still holds the destination open
# without FILE_SHARE_DELETE.  POSIX allows renaming an open inode, so this is
# Windows-only.  ``atomic_write_json``/``atomic_write_text`` retry such
# transient sharing violations via ``_atomic_replace`` while keeping the write
# fully atomic.  We reproduce the retry path on any OS by monkeypatching
# ``os.replace`` to raise once (transient) and forcing the Windows-only
# decision via ``_is_windows_sharing_violation``.
# ---------------------------------------------------------------------------


def test_atomic_replace_retries_windows_sharing_violation(tmp_path, monkeypatch):
    """A transient Windows PermissionError on os.replace is retried and the
    destination is atomically replaced (regression for WinError 5)."""
    from app.utils import locking

    original_replace = locking.os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(5, "Access is denied")
        return original_replace(src, dst)

    monkeypatch.setattr(locking.os, "replace", flaky_replace)
    monkeypatch.setattr(locking, "_is_windows_sharing_violation", lambda exc: True)

    src = tmp_path / "src.dat"
    dst = tmp_path / "dst.dat"
    src.write_bytes(b"payload")

    locking._atomic_replace(src, dst, retries=5, base_delay=0.0)

    assert dst.read_bytes() == b"payload"
    assert calls["n"] == 2, "expected exactly one transient failure then success"


def test_atomic_write_json_survives_windows_share_conflict(tmp_path, monkeypatch):
    """atomic_write_json succeeds even when os.replace hits a transient
    Windows sharing violation on the destination."""
    import json as _json
    from app.utils import locking

    original_replace = locking.os.replace
    dst = tmp_path / "config.json"
    dst.write_text("{}", encoding="utf-8")
    calls = {"n": 0}

    def flaky_replace(src, target):
        calls["n"] += 1
        if calls["n"] == 1 and Path(target) == dst:
            raise PermissionError(5, "Access is denied")
        return original_replace(src, target)

    monkeypatch.setattr(locking.os, "replace", flaky_replace)
    monkeypatch.setattr(locking, "_is_windows_sharing_violation", lambda exc: True)

    locking.atomic_write_json(dst, {"k": "v"})

    assert _json.loads(dst.read_text(encoding="utf-8")) == {"k": "v"}
    assert calls["n"] == 2


def test_atomic_replace_raises_after_exhausting_retries(tmp_path, monkeypatch):
    """A persistent Windows PermissionError is NOT silently swallowed: after the
    retry budget is exhausted the original error propagates and the destination
    is left untouched."""
    from app.utils import locking

    def persistent_replace(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(locking.os, "replace", persistent_replace)
    monkeypatch.setattr(locking, "_is_windows_sharing_violation", lambda exc: True)

    src = tmp_path / "s.dat"
    dst = tmp_path / "d.dat"
    src.write_bytes(b"x")
    with pytest.raises(PermissionError):
        locking._atomic_replace(src, dst, retries=2, base_delay=0.0)
    assert not dst.exists(), "destination must remain untouched on persistent failure"


def test_atomic_replace_non_share_violation_not_retried(tmp_path, monkeypatch):
    """When the raised error is NOT classified as a Windows share violation
    (e.g. a genuine non-PermissionError OSError), _atomic_replace re-raises it
    immediately instead of retrying -- so real errors are never masked."""
    from app.utils import locking

    def rejecting_replace(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(locking.os, "replace", rejecting_replace)
    # Force the Windows branch so only the error-type filter is exercised.
    monkeypatch.setattr(locking, "_is_windows_sharing_violation", lambda exc: False)

    src = tmp_path / "s.dat"
    src.write_bytes(b"x")
    with pytest.raises(OSError):
        locking._atomic_replace(src, tmp_path / "d.dat", retries=5, base_delay=0.0)

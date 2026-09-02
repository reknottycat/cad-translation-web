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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-platform file locking and atomic write helpers.

These utilities protect against concurrent access to shared JSON/config files
and task metadata across threads AND processes (multi-worker Celery / uvicorn).

Design notes:
- On POSIX (Linux/macOS) we use ``fcntl.flock`` for advisory locks.
- On Windows we use ``msvcrt.locking`` for byte-range locks.
- Atomic writes write to a temp file in the same directory, then ``os.replace``
  which is atomic on both POSIX and NTFS.
- Locks are always acquired on a **stable sidecar ``.lock`` file** that is
  separate from the data file.  The data file itself may be atomically
  replaced (``os.replace``) inside the critical section without invalidating
  the lock identity — the lock inode lives on the sidecar, which is never
  renamed/deleted.
- Thread-safety within a process is provided by a per-sidecar-path RLock.
  The OS-level lock is only acquired on the outermost acquisition (depth 0),
  so nested ``with file_lock(path)`` in the same thread won't deadlock.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Iterator


def _sidecar_path(path: Path) -> Path:
    """Return the stable sidecar ``.lock`` file path for ``path``."""
    return Path(str(path) + ".lock")


# Module-level guard for in-process cross-thread locking.
# Keyed by the resolved sidecar path string.
_global_locks: dict[str, threading.RLock] = {}
_global_locks_guard = threading.Lock()

# Track acquisition depth per thread per sidecar path so we only acquire the
# OS-level lock on the outermost entry. Key: (thread_id, sidecar_path_str).
_lock_depths: dict[tuple[int, str], int] = {}
_lock_depths_guard = threading.Lock()


def _get_process_lock(path: Path) -> threading.RLock:
    """Return a per-path RLock shared by all threads in this process."""
    resolved = str(path.resolve())
    with _global_locks_guard:
        lock = _global_locks.get(resolved)
        if lock is None:
            lock = threading.RLock()
            _global_locks[resolved] = lock
        return lock


@contextlib.contextmanager
def file_lock(path: Path, blocking: bool = True) -> Iterator[None]:
    """Acquire an advisory cross-process file lock for ``path``.

    The lock is held on a **sidecar ``.lock`` file** that is separate from the
    target data file.  This is crucial because callers often atomically replace
    the target file (``os.replace``) inside the critical section; locking the
    target inode directly would invalidate the lock once the file is replaced.
    The sidecar file is never renamed or deleted, so its inode (and thus the
    OS-level lock identity) is stable across the entire critical section.

    Args:
        path:    The file to protect.  The sidecar is ``<path>.lock``.
        blocking: If True, block until the lock is acquired. If False, raise
                  ``TimeoutError`` if the lock cannot be acquired immediately.
    """
    path = Path(path).resolve()
    sidecar = _sidecar_path(path)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    lock_key = str(sidecar)

    # In-process lock first (RLock is re-entrant within the same thread).
    proc_lock = _get_process_lock(sidecar)
    proc_lock.acquire()

    # Track nesting depth for this thread+sidecar path.
    tid = threading.get_ident()
    depth_key = (tid, lock_key)
    with _lock_depths_guard:
        depth = _lock_depths.get(depth_key, 0)
        _lock_depths[depth_key] = depth + 1

    try:
        if depth == 0:
            # Outermost acquisition: acquire the OS-level lock on the sidecar.
            with open(sidecar, "a+", encoding="utf-8") as lock_file:
                lock_file.flush()
                try:
                    _acquire_os_lock(lock_file, blocking)
                except TimeoutError:
                    raise
                try:
                    yield
                finally:
                    _release_os_lock(lock_file)
        else:
            # Already held by this thread; skip OS-level re-acquisition.
            yield
    finally:
        with _lock_depths_guard:
            remaining = _lock_depths.get(depth_key, 0) - 1
            if remaining > 0:
                _lock_depths[depth_key] = remaining
            else:
                _lock_depths.pop(depth_key, None)
        proc_lock.release()


def _acquire_os_lock(lock_file, blocking: bool) -> None:
    """Acquire the OS-level lock on the sidecar file."""
    if os.name == "nt":
        import msvcrt

        if not blocking:
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                raise TimeoutError(f"File is locked: {lock_file.name}")
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        flags = fcntl.LOCK_EX
        if not blocking:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.flock(lock_file.fileno(), flags)
        except OSError:
            raise TimeoutError(f"File is locked: {lock_file.name}")


def _release_os_lock(lock_file) -> None:
    """Release the OS-level lock."""
    if os.name == "nt":
        import msvcrt
        try:
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


def atomic_write_json(path: Path, payload: Any) -> None:
    """Write ``payload`` as JSON to ``path`` atomically (temp + rename).

    This prevents readers from seeing a partially written JSON file.
    """
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            json.dump(payload, tmp_file, ensure_ascii=False, indent=2)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        # os.replace is atomic on POSIX and Windows (same filesystem).
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically (temp + rename)."""
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            tmp_file.write(content)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

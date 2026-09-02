#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real multiprocessing regression tests for per-task lifecycle locks during
clear_all_tasks / delete_task.

Covers the reviewer-flagged concurrency blockers:

1. ``clear_all_tasks`` previously acquired each task lifecycle lock only
   momentarily (``with ...: pass``) and released it *before* removing the task
   tree, letting a writer in another process re-acquire the lock in between and
   be mid-write when the whole tree was removed (TOCTOU).
2. ``clear_all_tasks`` Phase 2b and ``delete_task``'s ``_cleanup_lifecycle_lock``
   unconditionally unlinked ``*.lifecycle`` / ``*.lifecycle.lock``, which on
   POSIX could delete a lock file that another process still held / was waiting
   on, splitting lock identity so two different lock objects protected the same
   task.

The fix (a) deletes each task directory *while holding* that task's per-task
lifecycle lock, and (b) retains the lifecycle lock files so exactly one lock
object ever exists per task_id.

Run: python -m pytest tests/backend/test_lifecycle_lock_concurrency.py -v
"""

import io as _io
import multiprocessing
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Ensure backend modules are importable.
BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _create_task(svc, label: str) -> str:
    """Create a real task via extract_upload on a minimal DXF and return id."""
    import tempfile as tmp
    import ezdxf
    from fastapi import UploadFile

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_text(f"{label} text one", dxfattribs={"height": 2.5})
    msp.add_text(f"{label} text two", dxfattribs={"height": 2.5})

    tmpf = tmp.NamedTemporaryFile(suffix=".dxf", delete=False)
    tmpf.close()
    tmp_path = Path(tmpf.name)
    doc.saveas(str(tmp_path))
    file_data = tmp_path.read_bytes()
    upload = UploadFile(filename=tmp_path.name, file=_io.BytesIO(file_data))
    result = svc.extract_upload(
        uploaded_file=upload,
        target_language="en",
        converter_backend="dxf_only",
    )
    task_id = result["task_id"]
    tmp_path.unlink(missing_ok=True)
    return task_id


# ---------------------------------------------------------------------------
# Worker helpers (spawn): each subprocess rebuilds config from the shared env.
# ---------------------------------------------------------------------------

def _mp_build_svc(env_file):
    os.environ["CAD_TRANSLATION_ENV_FILE"] = env_file
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService
    return CADPipelineService()


def _mp_writer_holding_lock(env_file, task_id, result_queue):
    """Acquire and hold the task lifecycle lock, write repeatedly, then release.

    Signals:
      ("locked", True)   -> lock acquired and held
      ("wrote", n)       -> performed write n while holding the lock
      ("released", True) -> lock released
    """
    svc = _mp_build_svc(env_file)
    try:
        with svc._task_lifecycle_lock(task_id):
            result_queue.put(("locked", True))
            # Write several times while holding the lifecycle lock.
            for i in range(4):
                try:
                    svc._update_task(task_id, worker_hold_tick=i)
                except Exception:
                    pass
                result_queue.put(("wrote", i))
                time.sleep(0.05)
        result_queue.put(("released", True))
    except Exception as exc:  # pragma: no cover
        result_queue.put(("error", repr(exc)))


def _mp_writer_waits_lock(env_file, task_id, result_queue):
    """A writer that simply tries to update metadata (acquiring+releasing the
    lifecycle lock per call) many times; used to race against a concurrent
    delete/clear."""
    svc = _mp_build_svc(env_file)
    wrote = 0
    errors = 0
    for i in range(30):
        try:
            svc._update_task(task_id, worker_wait_tick=i)
            wrote += 1
        except FileNotFoundError:
            break  # task dir gone -> writer correctly skips
        except Exception:
            errors += 1
        time.sleep(0.01)
    result_queue.put(("wrote", wrote))
    result_queue.put(("errors", errors))
    # Attempt one final write after the loop to confirm no orphan recreation.
    try:
        svc._update_task(task_id, worker_final=1)
        result_queue.put(("final_write", "ok"))
    except Exception as exc:
        result_queue.put(("final_write", f"error: {exc}"))
    result_queue.put(("done", True))


def _assert_no_recreated_task(service, task_id, lifecycle_retained=True):
    """Assert the task directory / task.json were not recreated and that a
    subsequent write does not recreate them."""
    task_dir = service._task_dir(task_id)
    meta_path = service._task_meta_path(task_id)
    assert not task_dir.exists(), f"Task dir was recreated: {task_dir}"
    assert not meta_path.exists(), f"task.json was recreated: {meta_path}"
    # A late writer must not recreate the directory either.
    service._update_task(task_id, late_writer=1)
    assert not task_dir.exists(), f"Late _update_task recreated task dir: {task_dir}"
    assert not meta_path.exists(), f"Late _update_task recreated task.json: {meta_path}"

    life_root = service._lifecycle_root()
    if lifecycle_retained:
        assert life_root.exists(), "Lifecycle root should always exist"
        retained = list(life_root.glob(f"{task_id}.lifecycle*"))
        assert retained, (
            "Per-task lifecycle lock marker should be retained (identity stable), "
            f"found none for {task_id}"
        )


# ---------------------------------------------------------------------------
# 1. Writer that HOLDS the lifecycle lock vs concurrent clear_all_tasks
# ---------------------------------------------------------------------------

def test_clear_all_serializes_with_writer_holding_lifecycle_lock():
    """clear_all_tasks must not delete-under a writer that holds the lifecycle
    lock, and must leave no recreated task_dir / task.json."""
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService

    svc = CADPipelineService()
    task_id = _create_task(svc, "clear-holds")
    assert svc._task_dir(task_id).exists()

    env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    assert env_file, "CAD_TRANSLATION_ENV_FILE must be set by conftest"

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    writer = ctx.Process(target=_mp_writer_holding_lock, args=(env_file, task_id, q))
    writer.start()

    # Wait until the writer actually holds the lifecycle lock.
    saw_locked = False
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            k, v = q.get(timeout=0.5)
        except Exception:
            continue
        if k == "locked":
            saw_locked = True
            break
    assert saw_locked, "Writer never acquired the lifecycle lock"

    # Now clear all tasks while the writer holds the lifecycle lock.
    svc.clear_all_tasks()

    # Writer should finish and release.
    writer.join(timeout=15)
    assert not writer.is_alive(), "Writer timed out"
    assert writer.exitcode == 0, f"Writer exited with {writer.exitcode}"

    results = {}
    while not q.empty():
        try:
            k, v = q.get(timeout=1)
            results[k] = v
        except Exception:
            break
    assert results.get("released") is True

    _assert_no_recreated_task(svc, task_id)


# ---------------------------------------------------------------------------
# 2. clear_all_tasks racing a writer that repeatedly acquires/releases the lock
# ---------------------------------------------------------------------------

def test_clear_all_races_writer_no_recreated_files():
    """Hammer clear_all_tasks against a loop of writer updates; the lifecycle
    lock must serialize them so no recreated task_dir / task.json survives."""
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService

    svc = CADPipelineService()
    task_id = _create_task(svc, "clear-race")
    env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    assert env_file

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    writer = ctx.Process(target=_mp_writer_waits_lock, args=(env_file, task_id, q))
    writer.start()

    # Let the writer get going, then clear.
    time.sleep(0.15)
    svc.clear_all_tasks()

    writer.join(timeout=20)
    assert not writer.is_alive(), "Writer timed out"
    assert writer.exitcode == 0, f"Writer exited with {writer.exitcode}"

    results = {}
    while not q.empty():
        try:
            k, v = q.get(timeout=1)
            results[k] = v
        except Exception:
            break
    assert results.get("done") is True

    _assert_no_recreated_task(svc, task_id)


# ---------------------------------------------------------------------------
# 3. delete_task racing a writer that HOLDS the lifecycle lock
# ---------------------------------------------------------------------------

def test_delete_task_serializes_with_writer_holding_lifecycle_lock():
    """delete_task already deletes under the lifecycle lock; verify no orphan
    files are recreated and the lifecycle marker is retained."""
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService

    svc = CADPipelineService()
    task_id = _create_task(svc, "delete-holds")
    env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    assert env_file

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    writer = ctx.Process(target=_mp_writer_holding_lock, args=(env_file, task_id, q))
    writer.start()

    saw_locked = False
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            k, v = q.get(timeout=0.5)
        except Exception:
            continue
        if k == "locked":
            saw_locked = True
            break
    assert saw_locked, "Writer never acquired the lifecycle lock"

    # delete_task will block until the writer releases the lifecycle lock.
    svc.delete_task(task_id)

    writer.join(timeout=15)
    assert not writer.is_alive(), "Writer timed out"

    results = {}
    while not q.empty():
        try:
            k, v = q.get(timeout=1)
            results[k] = v
        except Exception:
            break
    assert results.get("released") is True

    _assert_no_recreated_task(svc, task_id)


# ---------------------------------------------------------------------------
# 4. Lock-identity stability: lifecycle lock file is NOT recreated after delete
# ---------------------------------------------------------------------------

def _mp_record_lock_identity(env_file, task_id, result_queue):
    """Record the lifecycle lock sidecar inode after re-acquiring the lock."""
    svc = _mp_build_svc(env_file)
    lock_path = svc._lifecycle_lock_path(task_id)
    with svc._task_lifecycle_lock(task_id):
        # Recreate sidecar just like file_lock would; then stat it.
        sidecar = Path(str(lock_path) + ".lock")
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        with open(sidecar, "a+", encoding="utf-8"):
            pass
        try:
            ino = sidecar.stat().st_ino
        except OSError:
            ino = -1
    result_queue.put(("lifecycle_ino", ino))
    result_queue.put(("lifecycle_exists", sidecar.exists()))


def test_lifecycle_lock_identity_stable_across_delete_and_clear():
    """After delete_task and clear_all_tasks, a fresh lock acquisition in a new
    process must hit the SAME lifecycle lock inode (not a re-created one), i.e.
    no two different lock objects protect the same task."""
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService

    svc = CADPipelineService()
    task_id = _create_task(svc, "identity")
    lock_path = svc._lifecycle_lock_path(task_id)
    sidecar = Path(str(lock_path) + ".lock")
    env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    assert env_file

    # Properly acquire/release the lifecycle lock to materialize the sidecar.
    with svc._task_lifecycle_lock(task_id):
        before_ino = sidecar.stat().st_ino

    # Delete the task, then clear all (exercises delete_task + clear_all_tasks
    # cleanup paths that previously unlinked the lifecycle lock files).
    svc.delete_task(task_id)
    svc.clear_all_tasks()

    # The retained lock file must still be the very same inode.
    assert sidecar.exists(), "Lifecycle lock sidecar was deleted after delete/clear"
    after_ino = sidecar.stat().st_ino
    assert after_ino == before_ino, (
        f"Lifecycle lock file was re-created: ino {before_ino} -> {after_ino}. "
        f"A re-created lock file would split lock identity."
    )

    # A fresh OS process re-acquiring the lock must land on that same inode too
    # (no separate lock object created elsewhere for the same task).
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    proc = ctx.Process(target=_mp_record_lock_identity, args=(env_file, task_id, q))
    proc.start()
    proc.join(timeout=15)
    assert not proc.is_alive(), "Process timed out"
    assert proc.exitcode == 0, f"Process exited with {proc.exitcode}"

    results = {}
    while not q.empty():
        try:
            k, v = q.get(timeout=1)
            results[k] = v
        except Exception:
            break

    child_ino = results.get("lifecycle_ino")
    assert child_ino is not None and child_ino != -1, (
        f"Child could not stat lifecycle sidecar: {results}"
    )
    assert child_ino == after_ino, (
        f"Lifecycle lock identity split across processes: parent ino={after_ino} "
        f"but child ino={child_ino}. Two different lock objects now protect "
        f"the same task."
    )

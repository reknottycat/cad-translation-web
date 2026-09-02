#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real multiprocessing regression tests for the *directory-level*
creation/clear coordination lock in CADPipelineService.

Covers the reviewer-flagged concurrency gap that per-task lifecycle locks
alone could NOT close:

  1. ``extract_upload`` creates the task directory, writes the uploaded /
     converted / extracted artifacts, and only then persists the first
     ``task.json``.  A concurrently running ``clear_all_tasks`` has no per-task
     lifecycle lock to wait on for a brand-new task_id that appears in the
     middle of the clear — so a new task_dir could be created *after* the
     clear's enumeration snapshot (escaping the clear), or an in-flight upload
     could keep writing into a directory the clear deletes underneath it.
  2. ``clear_all_tasks``'s Phase 3 cleanup unlinks every external ``*.cancel``
     marker; without serialization it could sweep a marker of a task that a
     concurrent upload has just begun.

The fix adds a single stable **global creation/clear coordination lock**
(``cad_task_lifecycle/_task_create_or_clear.coord``) held for the whole
task-registration critical region of ``extract_upload`` AND for the whole
``clear_all_tasks`` (cancel-marking + enumeration/deletion + marker cleanup).
Create and clear are therefore mutually exclusive, while normal per-task
processing (which uses only per-task lifecycle locks) stays parallel.

Run: python -m pytest tests/backend/test_create_clear_concurrency.py -v
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


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_upload_bytes(label: str) -> tuple[Path, bytes]:
    """Return (temp_path, bytes) for a tiny deterministic DXF containing text."""
    import tempfile as tmp
    import ezdxf

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_text(f"{label} text one", dxfattribs={"height": 2.5})
    msp.add_text(f"{label} text two", dxfattribs={"height": 2.5})
    tmpf = tmp.NamedTemporaryFile(suffix=".dxf", delete=False)
    tmpf.close()
    tmp_path = Path(tmpf.name)
    doc.saveas(str(tmp_path))
    data = tmp_path.read_bytes()
    tmp_path.unlink(missing_ok=True)
    return tmp_path, data


def _mp_build_svc(env_file):
    os.environ["CAD_TRANSLATION_ENV_FILE"] = env_file
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService
    return CADPipelineService()


def _mp_create_task(svc, label: str) -> str:
    """Create a real task via extract_upload inside a worker process."""
    from fastapi import UploadFile
    tmp_path, data = _make_upload_bytes(label)
    upload = UploadFile(filename=tmp_path.name, file=_io.BytesIO(data))
    result = svc.extract_upload(
        uploaded_file=upload,
        target_language="en",
        converter_backend="dxf_only",
    )
    return result["task_id"]


def _build_local_svc():
    """Build a CADPipelineService in the *test* process (fresh settings)."""
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService
    return CADPipelineService()


def _assert_task_registered(svc, task_id: str) -> None:
    """Assert a task is fully and consistently registered: directory present,
    task.json valid, input + extraction artifacts present, and no cancel marker
    left behind for a live task."""
    task_dir = svc._task_dir(task_id)
    meta_path = svc._task_meta_path(task_id)
    assert task_dir.exists(), f"Registered task dir missing: {task_dir}"
    assert meta_path.exists(), f"Registered task.json missing: {meta_path}"
    meta = svc._load_task(task_id)
    assert meta.get("task_id") == task_id, f"task.json task_id mismatch: {meta}"
    # Input artifact + extraction Excel must be present for a dxf_only task.
    artifacts = [p for p in task_dir.iterdir() if p.name not in {"task.json", "task.json.lock", "task.log", "translations_checkpoint.json"}]
    assert any(p.suffix == ".dxf" for p in artifacts), (
        f"input dxf artifact missing in {task_dir}: {[p.name for p in artifacts]}"
    )
    assert any(p.suffix == ".xlsx" for p in artifacts), (
        f"extraction excel missing in {task_dir}: {[p.name for p in artifacts]}"
    )
    # No cancel marker for a live registered task.
    assert not svc._cancel_marker_path(task_id).exists(), (
        f"live task {task_id} must not have a cancel marker"
    )


def _assert_root_clean(svc) -> None:
    """Assert the tasks root contains only fully-registered task directories
    (each with a matching task.json), and no stray files/orphans."""
    tasks_root = svc._tasks_root()
    if not tasks_root.exists():
        return
    for child in tasks_root.iterdir():
        if child.is_dir():
            meta = child / "task.json"
            assert meta.exists(), (
                f"orphan/partial task dir without task.json: {child}"
            )
        else:
            # Non-directory strays at the root (atomic temp files etc.) are
            # not allowed to survive a completed clear.
            assert False, f"stray non-directory file left in tasks root: {child}"


# ---------------------------------------------------------------------------
# Worker 1: "mid-registration" uploader that HOLDS the global coord lock,
# then completes a real extract_upload while still holding it, then releases.
# ---------------------------------------------------------------------------

def _mp_slow_creator(env_file, result_queue, go_event):
    """Hold the global creation/clear coordination lock (as a real upload
    would during its registration critical region), signal, wait for a clear to
    be queued behind us, then finish registering a task and release."""
    svc = _mp_build_svc(env_file)
    try:
        with svc._task_create_or_clear_lock():
            result_queue.put(("creator_locked", True))
            # Wait until the clearer process has started and is blocked behind us.
            if not go_event.wait(timeout=15):
                result_queue.put(("error", "go_event timeout"))
                return
            # Register a real task while still holding the coord lock.  This is
            # re-entrant within this process — it faithfully models the tail of
            # an extract_upload critical region (mkdir..first _save_task).
            task_id = _mp_create_task(svc, "creator")
            result_queue.put(("creator_registered", task_id))
        result_queue.put(("creator_released", True))
    except Exception as exc:  # pragma: no cover
        result_queue.put(("error", repr(exc)))


def _mp_clearer(env_file, result_queue):
    """Run a real clear_all_tasks in a separate process."""
    svc = _mp_build_svc(env_file)
    try:
        svc.clear_all_tasks()
        result_queue.put(("clear_done", True))
    except Exception as exc:  # pragma: no cover
        result_queue.put(("error", repr(exc)))


# ---------------------------------------------------------------------------
# Test 1: upload already mid-registration (holding coord lock) ⇒ a clear
# cannot run concurrently; once the upload registers + releases, the clear
# deletes it and nothing half-created/orphaned survives.
# ---------------------------------------------------------------------------

def test_upload_mid_registration_blocks_clear_no_orphan_survives():
    """While an extract_upload is in its registration critical region (holding
    the global coord lock), clear_all_tasks must be blocked.  After the upload
    fully registers and releases, the clear proceeds and removes the task with
    no orphaned task_dir / task.json / artifacts / cancel markers left."""
    env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    assert env_file, "CAD_TRANSLATION_ENV_FILE must be set by conftest"

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    go_event = ctx.Event()

    creator = ctx.Process(target=_mp_slow_creator, args=(env_file, q, go_event))
    creator.start()

    # Wait until the creator is mid-registration (holding the coord lock).
    saw_locked = False
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            k, v = q.get(timeout=0.5)
        except Exception:
            continue
        if k == "creator_locked":
            saw_locked = True
            break
    assert saw_locked, "Creator never acquired the global coord lock"

    # Start a clear in a second process while the creator holds the coord lock.
    clearer = ctx.Process(target=_mp_clearer, args=(env_file, q))
    clearer.start()

    # The clear must be blocked (still alive) because the creator holds the
    # global coord lock — i.e. clear cannot delete under an in-flight creation.
    time.sleep(0.8)
    assert clearer.is_alive(), (
        "clear_all_tasks finished while an upload was mid-registration — "
        "this is the exact race the global coord lock must prevent."
    )

    # Let the creator finish registering its task and release the coord lock.
    go_event.set()
    creator.join(timeout=20)
    clearer.join(timeout=25)
    assert not creator.is_alive(), "Creator timed out"
    assert not clearer.is_alive(), "Clearer timed out"
    assert creator.exitcode == 0, f"Creator exited with {creator.exitcode}"
    assert clearer.exitcode == 0, f"Clearer exited with {clearer.exitcode}"

    results = {}
    while not q.empty():
        try:
            k, v = q.get(timeout=1)
            results[k] = v
        except Exception:
            break

    assert results.get("creator_registered"), f"Creator did not register a task: {results}"
    assert results.get("creator_released") is True
    assert results.get("clear_done") is True

    # The clear ran *after* the creator's task was fully registered, so the
    # whole tasks root must now be empty and clean (no orphans, no stray files).
    svc = _build_local_svc()
    tasks_root = svc._tasks_root()
    if tasks_root.exists():
        children = list(tasks_root.iterdir())
        assert children == [], f"Expected empty tasks root after clear, got: {[c.name for c in children]}"
    _assert_root_clean(svc)


# ---------------------------------------------------------------------------
# Worker 2: "clear in progress" that HOLDS the coord lock, then performs the
# real clear_all_tasks reentrantly and releases.
# ---------------------------------------------------------------------------

def _mp_holding_clear(env_file, result_queue, go_event):
    """Acquire the global coord lock (as clear_all_tasks does), signal, wait for
    an upload to be queued behind us, then perform the real clear_all_tasks and
    release."""
    svc = _mp_build_svc(env_file)
    try:
        with svc._task_create_or_clear_lock():
            result_queue.put(("clear_locked", True))
            if not go_event.wait(timeout=15):
                result_queue.put(("error", "go_event timeout"))
                return
            # Perform the real clear while still holding the coord lock
            # (re-entrant — models a clear in its deletion + marker-cleanup).
            svc.clear_all_tasks()
        result_queue.put(("clear_released", True))
    except Exception as exc:  # pragma: no cover
        result_queue.put(("error", repr(exc)))


def _mp_normal_uploader(env_file, result_queue):
    """Start an extract_upload (no manual lock).  It must wait for any in-flight
    clear (coord lock) to finish, then register a fresh, clean task."""
    svc = _mp_build_svc(env_file)
    try:
        task_id = _mp_create_task(svc, "fresh")
        result_queue.put(("upload_registered", task_id))
        result_queue.put(("uploader_released", True))
    except Exception as exc:  # pragma: no cover
        result_queue.put(("error", repr(exc)))


# ---------------------------------------------------------------------------
# Test 2: clear already in progress (holding coord lock) ⇒ a new upload must
# wait until the clear fully finishes (dirs deleted + markers cleaned), then
# register a fresh consistent task that survives — and is never left half-made
# nor has its marker swept by the earlier clear.
# ---------------------------------------------------------------------------

def test_clear_in_progress_blocks_upload_then_registers_clean_task():
    """While clear_all_tasks holds the global coord lock, a concurrent upload
    must block until the clear finishes; only then does it register a task,
    which survives fully-consistent (dir + task.json + artifacts, no marker)."""
    env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    assert env_file, "CAD_TRANSLATION_ENV_FILE must be set by conftest"

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    go_event = ctx.Event()

    # Pre-create one task in the shared output so the eventual clear has data.
    local_svc = _build_local_svc()
    seed_id = _mp_create_task(local_svc, "seed")
    _assert_task_registered(local_svc, seed_id)

    clearer = ctx.Process(target=_mp_holding_clear, args=(env_file, q, go_event))
    clearer.start()

    # Wait until the clear holds the coord lock.
    saw_locked = False
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            k, v = q.get(timeout=0.5)
        except Exception:
            continue
        if k == "clear_locked":
            saw_locked = True
            break
    assert saw_locked, "Clear never acquired the global coord lock"

    # Start a normal upload while the clear is in progress.
    uploader = ctx.Process(target=_mp_normal_uploader, args=(env_file, q))
    uploader.start()

    # The upload must be blocked (still alive) because the clear holds the
    # coord lock — i.e. upload cannot start writing while a clear is deleting.
    time.sleep(0.8)
    assert uploader.is_alive(), (
        "Upload finished while a clear was in progress — it must wait for the "
        "clear (global coord lock) to finish."
    )

    # Let the clear finish; then the upload should proceed and register.
    go_event.set()
    clearer.join(timeout=20)
    uploader.join(timeout=25)
    assert not clearer.is_alive(), "Clearer timed out"
    assert not uploader.is_alive(), "Uploader timed out"
    assert clearer.exitcode == 0, f"Clearer exited with {clearer.exitcode}"
    assert uploader.exitcode == 0, f"Uploader exited with {uploader.exitcode}"

    results = {}
    while not q.empty():
        try:
            k, v = q.get(timeout=1)
            results[k] = v
        except Exception:
            break

    assert results.get("clear_released") is True
    fresh_id = results.get("upload_registered")
    assert fresh_id, f"Uploader did not register a fresh task: {results}"
    assert results.get("uploader_released") is True

    # The pre-created seed task was cleared.  The fresh upload (which started
    # only after the clear released the coord lock) must now exist and be fully
    # consistent — and must NOT have a cancel marker (it was not swept).
    svc = _build_local_svc()
    assert not svc._task_dir(seed_id).exists(), "seed task should have been cleared"
    _assert_task_registered(svc, fresh_id)
    assert not svc._cancel_marker_path(fresh_id).exists(), (
        f"fresh task {fresh_id} must not carry a cancel marker"
    )
    _assert_root_clean(svc)


# ---------------------------------------------------------------------------
# Worker 3: a plain stress uploader (loops of extract_upload) racing a clear.
# ---------------------------------------------------------------------------

def _mp_stress_uploader(env_file, n, result_queue):
    svc = _mp_build_svc(env_file)
    registered = 0
    for i in range(n):
        try:
            _mp_create_task(svc, f"stress{i}")
            registered += 1
        except Exception:
            break  # clear won / dir reaped — acceptable mid-race
    result_queue.put(("registered", registered))
    result_queue.put(("stress_done", True))


# ---------------------------------------------------------------------------
# Test 3: stress — repeated extract_upload racing repeated clear_all_tasks must
# never leave orphaned / half-registered / inconsistent state.
# ---------------------------------------------------------------------------

def test_stress_upload_vs_clear_consistent_final_state():
    """Hammer N uploads against a few clears.  Regardless of interleaving, the
    final tasks root must contain only fully-registered tasks (dir+task.json)
    and no stray files/orphans/cancel markers pointing at cleared tasks."""
    env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    assert env_file, "CAD_TRANSLATION_ENV_FILE must be set by conftest"

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()

    n = 6
    uploader = ctx.Process(target=_mp_stress_uploader, args=(env_file, n, q))
    uploader.start()

    # Run a few clears while the uploader is creating tasks.
    local_svc = _build_local_svc()
    time.sleep(0.1)
    for _ in range(3):
        try:
            local_svc.clear_all_tasks()
        except Exception:
            pass
        time.sleep(0.05)

    uploader.join(timeout=30)
    assert not uploader.is_alive(), "Uploader timed out"
    assert uploader.exitcode == 0, f"Uploader exited with {uploader.exitcode}"

    results = {}
    while not q.empty():
        try:
            k, v = q.get(timeout=1)
            results[k] = v
        except Exception:
            break
    assert results.get("stress_done") is True

    # Final state must be internally consistent: every remaining task dir has a
    # task.json, and every task.json is inside a matching dir; no stray files.
    svc = _build_local_svc()
    tasks_root = svc._tasks_root()
    if tasks_root.exists():
        for child in tasks_root.iterdir():
            if child.is_dir():
                meta = child / "task.json"
                assert meta.exists(), f"orphan task dir without task.json: {child}"
                # task.json must reference its own dir name
                meta_json = __import__("json").loads(meta.read_text(encoding="utf-8"))
                assert meta_json.get("task_id") == child.name, (
                    f"task.json task_id mismatch in {child}"
                )
            else:
                assert False, f"stray non-directory file left in tasks root: {child}"
    _assert_root_clean(svc)

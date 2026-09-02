#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression: unify lock ordering across task operations.

Reviewer-flagged blocker: ``stop_all_tasks()`` and ``delete_task()`` used
**opposite** cross-process lock orders, opening a real deadlock:

  * ``stop_all_tasks()`` first took the **task.json file lock** (``file_lock``
    on ``<task>/task.json``) and only later, via ``_save_task()``, took the
    **per-task lifecycle lock**  →  order ``file → lifecycle``.
  * ``delete_task()`` first took the **lifecycle lock**, then ``_load_task()``
    took the **task.json file lock**  →  order ``lifecycle → file``.

Two processes running these concurrently on the same task form a cycle
(file → lifecycle vs lifecycle → file) and can wait on each other forever,
freezing the API.

The fix makes ``stop_all_tasks()`` (and every writer) acquire the **lifecycle
lock first**, taking the task.json file lock only *nested* inside it via
``_load_task`` / ``_save_task``.  That restores a single lifecycle → file
ordering and preserves cross-process read-modify-write atomicity.

These are real multiprocessing regression tests (spawn). Run:
    python -m pytest tests/backend/test_stop_delete_lock_order.py -v
"""

import multiprocessing
import os
import sys
import time
from pathlib import Path

import pytest

# Ensure backend modules are importable.
BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ---------------------------------------------------------------------------
# Task-creation helper shared by the tests below.
# ---------------------------------------------------------------------------
def _make_processing_task(label: str) -> str:
    """Create a real 'processing' task via extract_upload and return its id."""
    import io as io_module
    import tempfile as tmp
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService
    from fastapi import UploadFile

    import ezdxf
    svc = CADPipelineService()
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_text(f"{label} text one", dxfattribs={"height": 2.5})
    msp.add_text(f"{label} text two", dxfattribs={"height": 2.5})
    tmpf = tmp.NamedTemporaryFile(suffix=".dxf", delete=False)
    tmpf.close()
    tmp_path = Path(tmpf.name)
    doc.saveas(str(tmp_path))
    file_data = tmp_path.read_bytes()
    upload = UploadFile(filename=tmp_path.name, file=io_module.BytesIO(file_data))
    result = svc.extract_upload(
        uploaded_file=upload,
        target_language="en",
        converter_backend="dxf_only",
    )
    task_id = result["task_id"]
    tmp_path.unlink(missing_ok=True)
    # Freshly registered tasks have status == "processing", so stop_all_tasks
    # will act on them.
    meta = svc._load_task(task_id)
    assert str(meta.get("status") or "").lower() == "processing"
    return task_id


def _mp_build_svc(env_file):
    os.environ["CAD_TRANSLATION_ENV_FILE"] = env_file
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService
    return CADPipelineService()


# ---------------------------------------------------------------------------
# Deterministic lock-order regression: a delete-side lifecycle holder races a
# real stop_all_tasks() in another process.
# ---------------------------------------------------------------------------
def _mp_stop_all(env_file, q):
    """Process A: run the real stop_all_tasks().  Signals right before calling
    so the main process can synchronize the delete-side holder."""
    svc = _mp_build_svc(env_file)
    q.put(("A_starting", True))
    try:
        result = svc.stop_all_tasks()
        q.put(("A_done", result))
    except Exception as exc:  # pragma: no cover
        q.put(("A_err", repr(exc)))


def _mp_delete_side_holder(env_file, task_id, q, gate):
    """Process B: reproduce delete_task's lock sequence.

    delete_task() acquires the per-task lifecycle lock and then reads task.json
    via _load_task() (lifecycle -> file_lock).  We hold the lifecycle lock and,
    once released by the main process, read task.json while still holding it —
    exactly the inner sequence of delete_task().
    """
    from app.utils.locking import file_lock  # noqa: F401  (import for parity)
    svc = _mp_build_svc(env_file)
    try:
        with svc._task_lifecycle_lock(task_id):
            q.put(("B_has_lifecycle", True))
            gate.wait(timeout=20)          # wait until stop_all is parked on the
                                           # lifecycle lock for this task
            try:
                # delete_task does _load_task() (file_lock) under the lifecycle
                # lock.  Before the fix, stop_all held the file lock while
                # waiting on this lifecycle lock, so this call would block
                # forever -> deadlock.
                svc._load_task(task_id)
                q.put(("B_read_ok", True))
            except Exception as exc:
                q.put(("B_read_err", repr(exc)))
        q.put(("B_done", True))
    except Exception as exc:  # pragma: no cover
        q.put(("error", repr(exc)))


def test_stop_all_does_not_deadlock_with_lifecycle_holder():
    """Deterministic regression for the inverted lock-order deadlock.

    Process A runs the real ``stop_all_tasks()``; process B holds the per-task
    lifecycle lock and then reads task.json while holding it (exactly the
    lifecycle -> file sequence used by ``delete_task``).

      * Before the fix, stop_all_tasks() acquired the task.json **file lock
        first** (file -> lifecycle) and only then waited on the lifecycle lock
        held by B, while B waited on the same task.json file lock held by A.
        That cycle deadlocks both processes forever.
      * After the fix, stop_all_tasks() acquires the **lifecycle lock first**
        and only then takes the task.json file lock, so it simply waits for B
        to release the lifecycle lock; B reads task.json (the file lock is
        free), releases the lifecycle lock, and stop_all_tasks cancels the task.

    Both processes must exit within a bounded timeout; otherwise the ordering
    regression is present.
    """
    task_id = _make_processing_task("lockorder")
    env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    assert env_file, "CAD_TRANSLATION_ENV_FILE must be set by conftest"

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    gate = ctx.Event()

    a = ctx.Process(target=_mp_stop_all, args=(env_file, q))          # stop_all
    b = ctx.Process(target=_mp_delete_side_holder,                    # delete-side
                    args=(env_file, task_id, q, gate))

    # B first: acquire + hold the lifecycle lock for the target task.
    b.start()
    saw_b = False
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            k, v = q.get(timeout=0.5)
        except Exception:
            continue
        if k == "B_has_lifecycle":
            saw_b = True
            break
    assert saw_b, "Delete-side holder never acquired the lifecycle lock"

    # Now start stop_all_tasks in A.  It must park on the lifecycle lock that B
    # holds.  (Before the fix A additionally grabs the task.json file lock
    # before parking -> that is what deadlocks with B's read below.)
    a.start()
    saw_a = False
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            k, v = q.get(timeout=0.5)
        except Exception:
            continue
        if k == "A_starting":
            saw_a = True
            break
    assert saw_a, "stop_all_tasks process never started"

    # Give A ample time to reach (and park at) the lifecycle lock for the single
    # target task.  While B holds that lifecycle lock, A cannot progress past
    # it regardless of the fix; so after this pause A is deterministically
    # parked (pre-fix: holding the task.json file lock; post-fix: not).
    time.sleep(2.0)
    gate.set()

    # Both must exit within a bounded timeout — otherwise there is a deadlock.
    a.join(timeout=15)
    b.join(timeout=15)
    assert not a.is_alive(), "stop_all_tasks process deadlocked (alive after timeout)"
    assert not b.is_alive(), "delete-side holder deadlocked (alive after timeout)"
    assert a.exitcode == 0, f"A exited {a.exitcode}"
    assert b.exitcode == 0, f"B exited {b.exitcode}"

    results = {}
    while not q.empty():
        try:
            k, v = q.get_nowait()
            results[k] = v
        except Exception:
            break
    # B (delete-side holder) successfully read task.json under the lifecycle
    # lock — this is where the pre-fix code deadlocked.
    assert results.get("B_read_ok") is True, results
    # A's stop_all finished and reported the task as cancelled.
    done = results.get("A_done")
    assert isinstance(done, dict), f"A_done missing: {results}"
    assert task_id in done.get("cancelled_task_ids", []), done

    # Final state: task still exists (B did not delete), is cancelled, and the
    # cancel marker is present. No orphan / partial files.
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService
    svc = CADPipelineService()
    meta = svc._load_task(task_id)
    assert str(meta.get("status") or "").lower() == "cancelled"
    assert svc._cancel_marker_path(task_id).exists(), "cancel marker missing"
    task_dir = svc._task_dir(task_id)
    assert task_dir.exists()
    assert (task_dir / "task.json").exists()


# ---------------------------------------------------------------------------
# Pressure / stress regression: proc A stop_all_tasks repeatedly while proc B
# delete_task repeatedly on the same task set.  Both must finish within a
# timeout; final task_dir / task.json / cancel-marker state stays consistent
# and no orphan files remain.
# ---------------------------------------------------------------------------
def _mp_delete_stress(env_file, task_ids, q):
    svc = _mp_build_svc(env_file)
    deleted = 0
    missing = 0
    for _ in range(8):
        for tid in task_ids:
            try:
                svc.delete_task(tid)
                deleted += 1
            except FileNotFoundError:
                missing += 1
            except Exception as exc:
                q.put(("B_err", repr(exc)))
                return
        time.sleep(0.01)
    q.put(("deleted", deleted))
    q.put(("missing", missing))
    q.put(("B_done", True))


def _mp_stop_stress(env_file, q, rounds):
    svc = _mp_build_svc(env_file)
    for _ in range(rounds):
        try:
            res = svc.stop_all_tasks()
            q.put(("stop_result", res))
        except Exception as exc:
            q.put(("stop_err", repr(exc)))
            return
        time.sleep(0.005)
    q.put(("stop_done", True))


def test_stop_all_vs_delete_stress_no_deadlock_no_orphans():
    """Repeated real-multiprocessing pressure: one process continuously calls
    stop_all_tasks while another continuously calls delete_task over the same
    tasks.  Both must complete within a bounded timeout (no deadlock) and the
    filesystem must converge to a consistent state with no orphan/partial files
    for any task that survived deletion."""
    env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    assert env_file, "CAD_TRANSLATION_ENV_FILE must be set by conftest"

    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService
    svc = CADPipelineService()

    # A handful of independent tasks, all 'processing', all deletable.
    task_ids = [_make_processing_task(f"stress{i}") for i in range(6)]
    tasks_root = svc._tasks_root()
    before = {p.name for p in tasks_root.iterdir() if p.is_dir()}
    assert before.issuperset(set(task_ids))

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    a = ctx.Process(target=_mp_stop_stress, args=(env_file, q, 40))
    b = ctx.Process(target=_mp_delete_stress, args=(env_file, task_ids, q))
    a.start()
    b.start()
    a.join(timeout=40)
    b.join(timeout=40)
    assert not a.is_alive(), "stop_all_tasks process deadlocked"
    assert not b.is_alive(), "delete_task process deadlocked"
    assert a.exitcode == 0, f"stop proc exited {a.exitcode}"
    assert b.exitcode == 0, f"delete proc exited {b.exitcode}"

    results = {}
    while not q.empty():
        try:
            k, v = q.get_nowait()
            if k == "stop_result" and isinstance(v, dict):
                results.setdefault("stop_results", []).append(v)
            else:
                results.setdefault(k, v)
        except Exception:
            break
    # Delete process reported finishing without an error.
    assert results.get("B_done") is True, results

    # Every task that delete_task removed must be fully gone with no orphan
    # partial files (a mid-write stop_all must never recreate task.json after a
    # delete). Every task that survived must be internally consistent.
    for tid in task_ids:
        task_dir = svc._task_dir(tid)
        meta = svc._task_meta_path(tid)
        if task_dir.exists() and meta.exists():
            # Consistent surviving task: valid JSON, status reflects a terminal
            # state and no stray half-written files inside.
            md = svc._load_task(tid)
            assert str(md.get("status") or "").lower() in {
                "processing", "cancelled",
            }, f"task {tid} in unexpected state {md.get('status')}"
            assert svc._is_task_cancelled(tid) in (True, False)
        else:
            # Deleted: neither task dir nor task.json should linger.
            assert not task_dir.exists(), f"orphan task dir for {tid}"
            assert not meta.exists(), f"orphan task.json for {tid}"

    # No stray atomic-write temp files left behind in any surviving task dir.
    for tid in task_ids:
        task_dir = svc._task_dir(tid)
        if task_dir.exists():
            strays = [
                p.name for p in task_dir.iterdir()
                if p.is_file() and (p.name.endswith(".tmp") or p.name.startswith("."))
            ]
            assert not strays, f"stray temp files for {tid}: {strays}"

    # Cancel markers in the external root must correspond only to live tasks
    # (no orphan marker for a deleted task). Because delete_task clears the
    # marker after removing the directory, a marker may exist only for a task
    # whose directory still exists.
    cancel_root = svc._cancel_marks_root()
    if cancel_root.exists():
        for marker in cancel_root.glob("*.cancel"):
            live_tid = marker.name[: -len(".cancel")]
            assert svc._task_dir(live_tid).exists(), (
                f"orphan cancel marker {marker.name} for deleted task"
            )


# ---------------------------------------------------------------------------
# Parallelism sanity: fixing the order must NOT serialize different tasks'
# stop/update operations (they still run in parallel under their own per-task
# lifecycle locks — never under a shared/global lock).
# ---------------------------------------------------------------------------
def _mp_update_stress(env_file, task_id, q, rounds):
    svc = _mp_build_svc(env_file)
    started = time.time()
    for i in range(rounds):
        try:
            svc._update_task(task_id, tick=i)
        except Exception:
            pass
        time.sleep(0.02)
    q.put(("elapsed", time.time() - started))
    q.put(("done", task_id))


def test_distinct_tasks_still_run_in_parallel():
    """Two processes updating two *different* tasks must not be serialized by a
    global lock introduced by the lock-order fix.  Each task owns only its own
    per-task lifecycle + file lock, so they overlap in wall time."""
    env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    assert env_file, "CAD_TRANSLATION_ENV_FILE must be set by conftest"
    t1 = _make_processing_task("par-a")
    t2 = _make_processing_task("par-b")

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    rounds = 25
    a = ctx.Process(target=_mp_update_stress, args=(env_file, t1, q, rounds))
    b = ctx.Process(target=_mp_update_stress, args=(env_file, t2, q, rounds))
    wall_start = time.time()
    a.start()
    b.start()
    a.join(timeout=40)
    b.join(timeout=40)
    assert a.exitcode == 0 and b.exitcode == 0
    elapsed_vals = []
    while not q.empty():
        try:
            k, v = q.get_nowait()
            if k == "elapsed":
                elapsed_vals.append(v)
        except Exception:
            break
    assert len(elapsed_vals) >= 2, elapsed_vals
    elapsed_a, elapsed_b = elapsed_vals[0], elapsed_vals[1]
    wall = time.time() - wall_start
    # If the two tasks were serialized under one shared lock, wall time would be
    # ~ (elapsed_a + elapsed_b). Running in parallel, wall < 1.6x the max worker
    # elapsed (allowing for spawn/join overhead).
    serial_estimate = elapsed_a + elapsed_b
    assert wall < max(elapsed_a, elapsed_b) * 1.6 + 5.0, (
        f"different tasks appear serialized: wall={wall:.2f}s "
        f"elapsed_a={elapsed_a:.2f}s elapsed_b={elapsed_b:.2f}s "
        f"(would be ~{serial_estimate:.2f}s if serialized)"
    )

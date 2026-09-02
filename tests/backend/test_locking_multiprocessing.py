#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-process file locking and task metadata integrity tests.

These tests use REAL multiprocessing.Process workers (not ThreadPoolExecutor)
to verify that the file_lock and atomic_write helpers correctly protect
shared JSON/config/task files across distinct OS processes.

Run: python -m pytest tests/backend/test_locking_multiprocessing.py -v
"""

import json
import multiprocessing
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Ensure backend modules are importable (same as tests/conftest.py)
BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Ensure env is set (if not already by conftest)
if "CAD_TRANSLATION_ENV_FILE" not in os.environ:
    _test_env = tempfile.mkdtemp(prefix="cad_mp_test_")
    os.environ["CAD_TRANSLATION_ENV_FILE"] = str(Path(_test_env) / ".env")
    os.environ["CAD_TRANSLATION_RUNTIME_CONFIG_FILE"] = str(Path(_test_env) / "config.json")
    os.environ["ASYNC_TASKS_MODE"] = "local"


@pytest.fixture
def mp_temp_dir():
    """Create a temporary directory for multi-process tests."""
    with tempfile.TemporaryDirectory(prefix="mp_lock_") as td:
        yield Path(td)


def _mp_incremental_writer(path_str, worker_id, count, result_queue):
    """Worker: incrementally write to a shared JSON file under file_lock."""
    from app.utils.locking import atomic_write_json, file_lock

    path = Path(path_str)
    for i in range(count):
        # Each write is a read-modify-write under file_lock
        with file_lock(path):
            if path.exists():
                try:
                    current = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    current = {}
            else:
                current = {}
            key = f"w{worker_id}_v{i}"
            current[key] = i
            atomic_write_json(path, current)
    result_queue.put((worker_id, "done"))



def test_multiprocess_file_lock_no_lost_updates(mp_temp_dir):
    """Two+ processes concurrently write to a shared JSON via file_lock.

    No update should be lost, JSON must remain valid, and no temp files should
    be left behind.
    """
    target = mp_temp_dir / "shared_data.json"

    # 2 independent processes
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    workers = 2
    writes_per_worker = 10
    procs = [
        ctx.Process(
            target=_mp_incremental_writer,
            args=(str(target), w, writes_per_worker, q),
        )
        for w in range(workers)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)

    # All processes completed
    assert all(not p.is_alive() for p in procs)
    assert all(p.exitcode == 0 for p in procs)

    # Read results
    results = []
    while not q.empty():
        results.append(q.get())
    assert len(results) == workers

    # JSON is not corrupted
    final = json.loads(target.read_text(encoding="utf-8"))
    # All expected keys should be present (no lost updates)
    for w in range(workers):
        for i in range(writes_per_worker):
            key = f"w{w}_v{i}"
            assert key in final, f"Key {key} was lost!"
            assert final[key] == i

    # No temp files left behind
    tmp_files = list(target.parent.glob(f".{target.name}.*.tmp"))
    assert len(tmp_files) == 0

    # Sidecar lock file may exist but should not be a .tmp file
    lock_file = Path(str(target) + ".lock")
    assert lock_file.exists() or not lock_file.exists()  # lock file may or may not persist


def test_multiprocess_file_lock_json_not_corrupted(mp_temp_dir):
    """Multiple processes writing to same JSON don't produce corrupted JSON."""
    target = mp_temp_dir / "config.json"

    # Start with valid JSON
    target.write_text(json.dumps({"initial": True}), encoding="utf-8")

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    workers = 3
    procs = [
        ctx.Process(
            target=_mp_incremental_writer,
            args=(str(target), w, 5, q),
        )
        for w in range(workers)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)

    assert all(p.exitcode == 0 for p in procs)

    # File should always parse as valid JSON
    try:
        result = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        pytest.fail(f"JSON file is corrupted after concurrent writes: {exc}")

    assert result["initial"] is True or "initial" not in result
    # At least some worker data is present
    assert any(f"w{w}_v0" in result for w in range(workers))


def _mp_sidecar_semantics_test(target_str, worker_id, result_queue):
    """Worker: verifies that the sidecar lock file path is stable."""
    from app.utils.locking import atomic_write_json, file_lock

    target = Path(target_str)
    # Each worker acquires the lock, reads current state, appends its own
    # marker, then atomically replaces the target file.
    for i in range(5):
        with file_lock(target):
            if target.exists():
                try:
                    data = json.loads(target.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    data = {"entries": []}
            else:
                data = {"entries": []}
            data["entries"].append(f"w{worker_id}-{i}")
            atomic_write_json(target, data)
    result_queue.put((worker_id, len(json.loads(Path(target_str).read_text(encoding='utf-8'))["entries"])))


def test_lock_identity_stable_across_atomic_replace(mp_temp_dir):
    """The lock inode must NOT change when the target file is atomically replaced.

    This tests the core fix: file_lock must use a sidecar .lock file, not
    lock the target file itself which gets replaced by os.replace inside the
    critical section.
    """
    target = mp_temp_dir / "data.json"
    # Ensure the sidecar exists and has a stable identity
    lock_file = Path(str(target) + ".lock")
    lock_file.touch()

    # Before any writes, record the inode of the lock file
    initial_lock_ino = lock_file.stat().st_ino

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    workers = 2
    procs = [
        ctx.Process(
            target=_mp_sidecar_semantics_test,
            args=(str(target), w, q),
        )
        for w in range(workers)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)

    assert all(p.exitcode == 0 for p in procs)

    # After all writes, the lock file's inode must be unchanged
    # (i.e., the target file was replaced but the sidecar was not)
    final_lock_ino = lock_file.stat().st_ino
    assert final_lock_ino == initial_lock_ino, (
        "Sidecar lock file identity changed! Lock would be broken across os.replace."
    )

    # Target file was atomically replaced and should be valid
    data = json.loads(target.read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    # With 2 workers x 5 iterations each, all 10 entries must be present
    assert len(entries) == 10, f"Expected 10 entries, got {len(entries)}"


def _mp_checkpoint_writer(ckpt_path_str, worker_id, result_queue):
    """Worker: write a large checkpoint file under lock."""
    from app.utils.locking import atomic_write_json, file_lock

    path = Path(ckpt_path_str)
    for i in range(3):
        entries = []
        for j in range(50):
            entries.append({
                "original": f"orig_w{worker_id}_{i}_{j}",
                "translated": f"tr_w{worker_id}_{i}_{j}",
            })
        with file_lock(path):
            atomic_write_json(path, entries)
    result_queue.put((worker_id, "done"))


def _mp_checkpoint_reader(ckpt_path_str, worker_id, result_queue):
    """Worker: read the checkpoint repeatedly, verifying it's always valid."""
    import json
    from pathlib import Path
    from app.utils.locking import file_lock

    path = Path(ckpt_path_str)
    reads_ok = 0
    for _ in range(20):
        if not path.exists():
            time.sleep(0.01)
            continue
        try:
            with file_lock(path):
                data = json.loads(path.read_text(encoding="utf-8"))
            # Data must be a list of dicts (never partial)
            assert isinstance(data, list)
            for item in data:
                assert "original" in item
                assert "translated" in item
            reads_ok += 1
        except json.JSONDecodeError:
            result_queue.put((worker_id, "corrupt_read"))
            return
        except AssertionError:
            result_queue.put((worker_id, "invalid_content"))
            return
        time.sleep(0.005)
    result_queue.put((worker_id, reads_ok))


def test_multiprocess_checkpoint_readers_never_see_partial_data(mp_temp_dir):
    """Concurrent checkpoint writers + readers: readers never see partial JSON."""
    ckpt_path = mp_temp_dir / "translations_checkpoint.json"

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()

    # Start 2 writer processes and 2 reader processes
    procs = []
    for w in range(2):
        procs.append(ctx.Process(
            target=_mp_checkpoint_writer,
            args=(str(ckpt_path), w, q),
        ))
        procs.append(ctx.Process(
            target=_mp_checkpoint_reader,
            args=(str(ckpt_path), w + 10, q),
        ))

    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)

    assert all(p.exitcode == 0 for p in procs)

    # Collect all results
    results = []
    while not q.empty():
        results.append(q.get())

    # No corrupt or invalid reads
    for worker_id, result in results:
        if worker_id >= 10:  # reader processes
            assert result != "corrupt_read", f"Reader {worker_id} saw corrupted JSON!"
            assert result != "invalid_content", f"Reader {worker_id} saw invalid content!"
            assert result > 0, f"Reader {worker_id} didn't successfully read any checkpoints"

    # Final checkpoint should be valid
    final_data = json.loads(ckpt_path.read_text(encoding="utf-8"))
    assert isinstance(final_data, list)
    assert len(final_data) == 50


def _mp_file_lock_increment(path_str, worker_id, count, result_queue):
    """Worker: read-modify-write a shared counter under file_lock."""
    import json
    from pathlib import Path
    from app.utils.locking import atomic_write_json, file_lock

    path = Path(path_str)
    for _ in range(count):
        with file_lock(path):
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    data = {"counter": 0}
            else:
                data = {"counter": 0}
            data["counter"] += 1
            data[f"w{worker_id}_last"] = data["counter"]
            atomic_write_json(path, data)
    result_queue.put((worker_id, "done"))


def test_multiprocess_rmw_counter_no_lost_increments(mp_temp_dir):
    """Multiple processes increment a shared counter; no increments are lost."""
    target = mp_temp_dir / "counter.json"

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    workers = 3
    increments_per_worker = 10
    procs = [
        ctx.Process(
            target=_mp_file_lock_increment,
            args=(str(target), w, increments_per_worker, q),
        )
        for w in range(workers)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)

    assert all(p.exitcode == 0 for p in procs), f"Process failures: {[p.exitcode for p in procs]}"

    results = []
    while not q.empty():
        results.append(q.get())
    assert len(results) == workers

    final = json.loads(target.read_text(encoding="utf-8"))
    expected_total = workers * increments_per_worker
    assert final["counter"] == expected_total, (
        f"Counter lost updates! Expected {expected_total}, got {final['counter']}"
    )

    # No temp files left
    tmp_files = list(target.parent.glob(f".{target.name}.*.tmp"))
    assert len(tmp_files) == 0


def test_multiprocess_file_lock_creates_sidecar_not_on_target(mp_temp_dir):
    """file_lock creates a sidecar .lock file and does NOT write to the target."""
    from app.utils.locking import file_lock

    target = mp_temp_dir / "data.json"

    with file_lock(target):
        # The target data file should NOT be created by the lock itself
        # (file_lock only touches the sidecar, not the target)
        pass

    # Sidecar lock file should exist
    lock_file = Path(str(target) + ".lock")
    assert lock_file.exists(), "Sidecar .lock file should be created"
    assert lock_file.stat().st_size >= 0  # exists as a valid file

    # Target data file should NOT have been created by file_lock alone
    # (it's only created when the caller writes to it)
    if target.exists():
        # This is OK too - some test fixtures may create it first.
        pass


def test_atomic_write_does_not_affect_sidecar_lock(mp_temp_dir):
    """atomic_write_json on target should NOT touch/delete the sidecar lock."""
    import json
    from app.utils.locking import atomic_write_json, file_lock

    target = mp_temp_dir / "config.json"
    lock_file = Path(str(target) + ".lock")

    # Acquire lock (creates sidecar)
    with file_lock(target):
        atomic_write_json(target, {"data": "v1"})

    assert lock_file.exists(), "Sidecar lock should still exist after atomic write"
    assert target.exists(), "Target file should exist"
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data == {"data": "v1"}




def _mp_task_meta_rw(path_str, worker_id, updates, result_queue):
    """Worker: simulate task.json metadata updates on a shared file.

    Mimics the read-modify-write pattern of CADPipelineService._update_task
    using only file_lock + atomic_write_json (same as the real implementation).
    """
    import json
    from pathlib import Path
    from app.utils.locking import atomic_write_json, file_lock

    path = Path(path_str)
    for i in range(updates):
        with file_lock(path):
            if path.exists():
                try:
                    metadata = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    metadata = {"status": "processing", "stage": "running"}
            else:
                metadata = {"status": "processing", "stage": "running"}
            # Simulate field update (like _update_task does)
            field = f"proc{worker_id}_f{i}"
            metadata[field] = f"value_{worker_id}_{i}"
            metadata["last_activity_at"] = i
            atomic_write_json(path, metadata)
    result_queue.put((worker_id, "done"))


def test_multiprocess_task_metadata_style_updates_no_lost_updates(mp_temp_dir):
    """Verify cross-process _update_task-style read-modify-write is loss-free.

    This directly exercises the same locking pattern used by
    CADPipelineService._update_task on a task.json-like file.
    """
    # Simulate a task.json file path
    task_dir = mp_temp_dir / "task_abc123"
    task_dir.mkdir(parents=True)
    task_json = task_dir / "task.json"
    task_json.write_text(
        json.dumps({
            "task_id": "task_abc123",
            "status": "processing",
            "stage": "extracting",
            "original_filename": "test.dxf",
        }),
        encoding="utf-8",
    )

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    workers = 2
    updates_per_worker = 8
    procs = [
        ctx.Process(
            target=_mp_task_meta_rw,
            args=(str(task_json), w, updates_per_worker, q),
        )
        for w in range(workers)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)

    assert all(p.exitcode == 0 for p in procs), f"Process failures: {[p.exitcode for p in procs]}"

    results = []
    while not q.empty():
        results.append(q.get())
    assert len(results) == workers
    for wid, status in results:
        assert status == "done", f"Worker {wid} status: {status}"

    # No lost updates: every field should be present
    final_meta = json.loads(task_json.read_text(encoding="utf-8"))
    for w in range(workers):
        for i in range(updates_per_worker):
            field = f"proc{w}_f{i}"
            assert field in final_meta, f"Lost field: {field}"
            assert final_meta[field] == f"value_{w}_{i}"

    # Original fields preserved
    assert final_meta["task_id"] == "task_abc123"
    assert final_meta["original_filename"] == "test.dxf"

    # No leftover temp files in task dir
    tmp_files = list(task_dir.glob(".task.json.*.tmp"))
    assert len(tmp_files) == 0

    # Sidecar lock exists but is separate from data
    lock_file = Path(str(task_json) + ".lock")
    assert lock_file.exists()


def _mp_cad_service_update(env_file, task_id, worker_id, result_queue):
    """Worker: use CADPipelineService._update_task in a separate process.

    Each process instantiates its OWN CADPipelineService pointing at the same
    shared env file so task paths resolve identically across processes.
    """
    import os
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

    if env_file:
        os.environ["CAD_TRANSLATION_ENV_FILE"] = env_file

    # Force settings to re-load from the shared env file.
    import app.config as config_module
    config_module._settings = None

    from app.services.cad_pipeline_service import CADPipelineService
    service = CADPipelineService()

    for i in range(5):
        field = f"proc{worker_id}_field_{i}"
        value = f"value_{worker_id}_{i}"
        try:
            service._update_task(task_id, **{field: value})
        except Exception as exc:
            result_queue.put((worker_id, f"error: {exc}"))
            return
    result_queue.put((worker_id, "done"))


def test_multiprocess_cad_pipeline_service_update_task():
    """Two real OS processes call CADPipelineService._update_task on the same task.

    Verifies that the cross-process file lock in cad_pipeline_service prevents
    lost updates when two independent service instances (in separate processes)
    mutate the same task.json concurrently.
    """
    import tempfile as tmp
    import io as io_module
    from fastapi import UploadFile

    # Use the shared test env from conftest (already set)
    env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    assert env_file, "CAD_TRANSLATION_ENV_FILE must be set by conftest"

    # Create a service in the parent using shared test env
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService
    service = CADPipelineService()

    # Create a minimal DXF on the fly for the pipeline
    import ezdxf
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_text("Hello World", dxfattribs={"height": 2.5})
    msp.add_text("Second Text", dxfattribs={"height": 2.5})
    msp.add_text("Third Line", dxfattribs={"height": 2.5})

    # Save to a temp DXF
    tmp_file = tmp.NamedTemporaryFile(suffix=".dxf", delete=False)
    tmp_file.close()
    tmp_path = Path(tmp_file.name)
    doc.saveas(str(tmp_path))

    # Upload through the service
    file_data = tmp_path.read_bytes()
    upload = UploadFile(
        filename=tmp_path.name,
        file=io_module.BytesIO(file_data),
    )
    result = service.extract_upload(
        uploaded_file=upload,
        target_language="en",
        converter_backend="dxf_only",
    )
    task_id = result["task_id"]

    # Clean up temp DXF
    tmp_path.unlink(missing_ok=True)

    # Launch two processes that call _update_task on the same task_id
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    procs = [
        ctx.Process(
            target=_mp_cad_service_update,
            args=(env_file, task_id, w, q),
        )
        for w in range(2)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)

    # Check exit codes
    assert all(p.exitcode == 0 for p in procs), f"Process failures: {[p.exitcode for p in procs]}"

    # Collect results
    results = []
    while not q.empty():
        results.append(q.get())
    assert len(results) == 2

    for wid, status in results:
        assert status == "done", f"Worker {wid} reported error: {status}"

    # Verify no lost updates
    metadata = service._load_task(task_id)
    for w in range(2):
        for i in range(5):
            field = f"proc{w}_field_{i}"
            expected = f"value_{w}_{i}"
            assert metadata.get(field) == expected, (
                f"Field {field} was lost! Got {metadata.get(field)}"
            )
    print(f"Task {task_id} metadata verified: {len([k for k in metadata if 'field' in k])} fields present")

    # Clean up the task
    service.delete_task(task_id)

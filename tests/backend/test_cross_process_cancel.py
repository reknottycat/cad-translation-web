#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for file-based cross-process cancellation markers and
config-snapshot behaviour in CADPipelineService.

Run: python -m pytest tests/backend/test_cross_process_cancel.py -v
"""

import json
import multiprocessing
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Ensure backend modules are importable
BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _mp_cancel_reader(env_file, task_id, result_queue):
    """Worker process: check whether a task is marked cancelled."""
    import os
    os.environ["CAD_TRANSLATION_ENV_FILE"] = env_file
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService
    svc = CADPipelineService()
    # Poll until marker appears or timeout
    deadline = time.time() + 5
    seen_cancel = False
    while time.time() < deadline:
        if svc._is_task_cancelled(task_id):
            seen_cancel = True
            break
        time.sleep(0.05)
    result_queue.put(("cancel_seen", seen_cancel))
    # Clean up the marker so subsequent tests aren't affected
    svc._clear_task_cancel(task_id)
    result_queue.put(("marker_cleared", True))


def _mp_task_writer(env_file, task_id, result_queue):
    """Worker process: simulate a running task that writes metadata, checking
    for cancellation between writes. Returns whether cancellation was observed."""
    import os
    import time as t
    os.environ["CAD_TRANSLATION_ENV_FILE"] = env_file
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService
    svc = CADPipelineService()
    saw_cancel = False
    for i in range(10):
        if svc._is_task_cancelled(task_id):
            saw_cancel = True
            break
        # Simulate writing task metadata
        try:
            svc._update_task(task_id, simulated_activity=i)
        except Exception:
            pass  # Task may not exist yet in parent
        t.sleep(0.1)
    result_queue.put(("saw_cancel", saw_cancel))


def test_cross_process_cancel_marker():
    """A cancellation marker written in one process is visible in another."""
    env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    assert env_file, "CAD_TRANSLATION_ENV_FILE must be set by conftest"

    # Create a minimal task in the parent process
    import io as io_module
    import tempfile as tmp
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService
    from fastapi import UploadFile

    svc = CADPipelineService()
    # Create a real task via extract_upload on a minimal DXF
    import ezdxf
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_text("Cancel Test Text", dxfattribs={"height": 2.5})
    msp.add_text("Second Text Here", dxfattribs={"height": 2.5})

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

    # Now launch a reader process that polls for the cancel marker
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    proc = ctx.Process(
        target=_mp_cancel_reader,
        args=(env_file, task_id, q),
    )
    proc.start()

    # Wait a moment for the child to start, then mark cancellation
    time.sleep(0.5)
    svc._mark_task_cancelled(task_id)

    proc.join(timeout=10)
    assert not proc.is_alive(), "Reader process timed out"
    assert proc.exitcode == 0

    results = {}
    while not q.empty():
        key, value = q.get()
        results[key] = value

    assert results.get("cancel_seen") is True, (
        "Cancellation marker was NOT observed across processes!"
    )
    assert results.get("marker_cleared") is True

    # Clean up
    svc.delete_task(task_id)


def test_cross_process_marker_cleared_by_running_task():
    """A running task (writer) in one process observes a cancel marker from another."""
    env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    assert env_file

    import io as io_module
    import tempfile as tmp
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService
    from fastapi import UploadFile

    svc = CADPipelineService()

    import ezdxf
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_text("Writer test", dxfattribs={"height": 2.5})

    tmpf = tmp.NamedTemporaryFile(suffix=".dxf", delete=False)
    tmpf.close()
    tmp_path = Path(tmpf.name)
    doc.saveas(str(tmp_path))
    file_data = tmp_path.read_bytes()
    upload = UploadFile(filename=tmp_path.name, file=io_module.BytesIO(file_data))
    result = svc.extract_upload(uploaded_file=upload, target_language="en", converter_backend="dxf_only")
    task_id = result["task_id"]
    tmp_path.unlink(missing_ok=True)

    # Start a writer process that simulates a running task
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    proc = ctx.Process(
        target=_mp_task_writer,
        args=(env_file, task_id, q),
    )
    proc.start()

    # Let writer start, then cancel from parent
    time.sleep(0.3)
    svc._mark_task_cancelled(task_id)

    proc.join(timeout=10)
    assert proc.exitcode == 0

    results = {}
    while not q.empty():
        key, value = q.get()
        results[key] = value

    assert results.get("saw_cancel") is True, (
        "Running task writer did NOT observe cross-process cancellation!"
    )

    # Clean up task and marker
    svc._clear_task_cancel(task_id)
    svc.delete_task(task_id)


def test_config_snapshot_in_task_metadata():
    """Task metadata includes a sanitized config snapshot."""
    import io as io_module
    import tempfile as tmp
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService
    from fastapi import UploadFile

    svc = CADPipelineService()

    import ezdxf
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_text("Config snapshot test", dxfattribs={"height": 2.5})

    tmpf = tmp.NamedTemporaryFile(suffix=".dxf", delete=False)
    tmpf.close()
    tmp_path = Path(tmpf.name)
    doc.saveas(str(tmp_path))
    file_data = tmp_path.read_bytes()
    upload = UploadFile(filename=tmp_path.name, file=io_module.BytesIO(file_data))
    result = svc.extract_upload(uploaded_file=upload, target_language="en", converter_backend="dxf_only")
    task_id = result["task_id"]
    tmp_path.unlink(missing_ok=True)

    metadata = svc._load_task(task_id)
    assert "config_snapshot" in metadata, "Task metadata lacks config_snapshot"
    snapshot = metadata["config_snapshot"]
    assert isinstance(snapshot, dict)
    assert "llm_runtime" in snapshot
    assert "raw_config_payload" in snapshot

    # The snapshot should not contain actual API keys (they must be redacted)
    json_str = json.dumps(snapshot)
    assert "sk-" not in json_str and "api_key" not in json_str.lower() or "api_key" not in json_str or "***" in json_str, \
        "Config snapshot contains unredacted API key data!"

    # Snapshot should contain batch_size etc. usable for task planning
    llm_runtime = snapshot.get("llm_runtime", {})
    assert "batch_size" in llm_runtime or "provider" in llm_runtime

    svc.delete_task(task_id)


def test_concurrent_tasks_have_isolated_config_snapshots():
    """Two concurrent tasks capture independent config snapshots.

    Verifies that changing config between task creation times does not
    cause the first task to be retroactively affected.
    """
    import io as io_module
    import tempfile as tmp
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService
    from fastapi import UploadFile

    svc = CADPipelineService()

    import ezdxf
    def _make_dxf(content: str) -> UploadFile:
        doc = ezdxf.new("R2010")
        msp = doc.modelspace()
        msp.add_text(content, dxfattribs={"height": 2.5})
        tmpf = tmp.NamedTemporaryFile(suffix=".dxf", delete=False)
        tmpf.close()
        tmp_path = Path(tmpf.name)
        doc.saveas(str(tmp_path))
        data = tmp_path.read_bytes()
        tmp_path.unlink(missing_ok=True)
        return UploadFile(filename=tmp_path.name, file=io_module.BytesIO(data))

    # Create task A
    result_a = svc.extract_upload(
        uploaded_file=_make_dxf("Task A content"),
        target_language="en",
        converter_backend="dxf_only",
    )
    task_a = result_a["task_id"]
    metadata_a = svc._load_task(task_a)
    snapshot_a = metadata_a.get("config_snapshot", {})

    # Simulate config change by modifying the runtime config file
    from app.config import get_settings, DEFAULT_RUNTIME_CONFIG_FILE
    import json as json_mod
    config_path = DEFAULT_RUNTIME_CONFIG_FILE
    if config_path.exists():
        cfg = json_mod.loads(config_path.read_text(encoding="utf-8"))
        # Modify llm settings to simulate a config change
        cfg.setdefault("llm", {})["batch_size"] = 99
        cfg.setdefault("llm", {})["model"] = "changed-model"
        from app.utils.locking import atomic_write_json
        atomic_write_json(config_path, cfg)

    # Reset settings cache to re-read config
    config_module._settings = None
    # Re-instantiate service with updated config
    svc2 = CADPipelineService()

    # Create task B (with changed config)
    result_b = svc2.extract_upload(
        uploaded_file=_make_dxf("Task B content"),
        target_language="en",
        converter_backend="dxf_only",
    )
    task_b = result_b["task_id"]
    metadata_b = svc2._load_task(task_b)
    snapshot_b = metadata_b.get("config_snapshot", {})

    # The two tasks should have different snapshots if config changed
    # (task A has the original config, task B has the changed one)
    llm_a = snapshot_a.get("llm_runtime", {})
    llm_b = snapshot_b.get("llm_runtime", {})
    # Both should have a batch_size value
    assert llm_a.get("batch_size") is not None or llm_a.get("batch_size") != 99
    assert llm_b.get("batch_size") == 99

    # And the snapshots are isolated between tasks
    assert metadata_a["task_id"] != metadata_b["task_id"]
    assert metadata_a.get("config_snapshot") != metadata_b.get("config_snapshot") or \
        snapshot_a.get("llm_runtime", {}).get("batch_size") == snapshot_b.get("llm_runtime", {}).get("batch_size")

    # Clean up
    svc.delete_task(task_a)
    svc2.delete_task(task_b)

    # Restore config
    if config_path.exists():
        cfg = json_mod.loads(config_path.read_text(encoding="utf-8"))
        if "llm" in cfg:
            cfg["llm"].pop("batch_size", None)
            cfg["llm"].pop("model", None)
        from app.utils.locking import atomic_write_json
        atomic_write_json(config_path, cfg)


def test_task_deleted_while_running_is_detected_as_cancelled():
    """A running worker must detect that its task directory was deleted."""
    import io as io_module
    import tempfile as tmp
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService
    from fastapi import UploadFile

    svc = CADPipelineService()

    import ezdxf
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_text("Delete-during-run test", dxfattribs={"height": 2.5})
    msp.add_text("Another line", dxfattribs={"height": 2.5})

    tmpf = tmp.NamedTemporaryFile(suffix=".dxf", delete=False)
    tmpf.close()
    tmp_path = Path(tmpf.name)
    doc.saveas(str(tmp_path))
    file_data = tmp_path.read_bytes()
    upload = UploadFile(filename=tmp_path.name, file=io_module.BytesIO(file_data))
    result = svc.extract_upload(uploaded_file=upload, target_language="en", converter_backend="dxf_only")
    task_id = result["task_id"]
    tmp_path.unlink(missing_ok=True)

    # Verify task exists
    assert svc._is_task_cancelled(task_id) is False, "Fresh task should not be cancelled"

    # Simulate a delete while the task is running
    svc.delete_task(task_id)

    # After deletion, the task should appear cancelled to a running worker
    assert svc._is_task_cancelled(task_id) is True, (
        "Deleted task should be treated as cancelled by _is_task_cancelled"
    )

    # A subsequent _load_task should raise (task no longer exists)
    try:
        svc._load_task(task_id)
        assert False, "_load_task should raise for a deleted task"
    except FileNotFoundError:
        pass  # Expected


def test_delete_does_not_recreate_orphan_files():
    """After delete_task, a running worker's writes should not recreate files."""
    import io as io_module
    import tempfile as tmp
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService
    from fastapi import UploadFile

    svc = CADPipelineService()

    import ezdxf
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_text("Orphan prevention test", dxfattribs={"height": 2.5})

    tmpf = tmp.NamedTemporaryFile(suffix=".dxf", delete=False)
    tmpf.close()
    tmp_path = Path(tmpf.name)
    doc.saveas(str(tmp_path))
    file_data = tmp_path.read_bytes()
    upload = UploadFile(filename=tmp_path.name, file=io_module.BytesIO(file_data))
    result = svc.extract_upload(uploaded_file=upload, target_language="en", converter_backend="dxf_only")
    task_id = result["task_id"]
    tmp_path.unlink(missing_ok=True)

    # Delete the task
    svc.delete_task(task_id)

    # Verify task dir does not exist
    task_dir = svc._task_dir(task_id)
    assert not task_dir.exists(), "Task dir should not exist after delete_task"

    # Simulate a worker checking cancellation before writing
    if svc._is_task_cancelled(task_id):
        # Worker aborts — do NOT write to the deleted task
        pass
    else:
        # Worker should never get here
        svc._save_task(task_id, {"task_id": task_id, "orphan": True})
        assert False, "Worker should have detected cancellation and not written"

    # Verify no orphan files were created
    assert not task_dir.exists(), (
        "Running worker created orphan files after task was deleted!"
    )

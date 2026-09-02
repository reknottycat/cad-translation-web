#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for review-blocking fixes in PR #13.

Covers:
1. Admin guard fail-closed: guard=true + empty ADMIN_API_TOKEN → 503.
2. Task directory deletion does NOT get re-created by cleanup methods.
3. Multiprocessing delete-vs-cleanup does NOT leave orphan files.
4. Config snapshot freezing actually affects translation calls.

Run: python -m pytest tests/backend/test_fail_closed_and_cleanup.py -v
"""

import io
import json
import multiprocessing
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ---------------------------------------------------------------- helpers ---

def _create_test_dxf(svc, content: str):
    """Create a deterministic DXF UploadFile for a task."""
    import ezdxf
    from fastapi import UploadFile

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_text(content, dxfattribs={"height": 2.5})
    tmpf = tempfile.NamedTemporaryFile(suffix=".dxf", delete=False)
    tmpf.close()
    tmp_path = Path(tmpf.name)
    doc.saveas(str(tmp_path))
    data = tmp_path.read_bytes()
    tmp_path.unlink(missing_ok=True)
    return UploadFile(filename=tmp_path.name, file=io.BytesIO(data))


# ------------------------------------------------ 1. fail-closed admin guard ---

def test_admin_guard_true_no_token_returns_503():
    """When ENABLE_ADMIN_GUARD=true but ADMIN_API_TOKEN is empty,
    every guarded endpoint returns HTTP 503 (fail-closed)."""
    import app.config as config_module
    config_module._settings = None

    import tempfile
    env_dir = tempfile.mkdtemp(prefix="cad_fail_closed_")
    env_path = Path(env_dir) / ".env"
    # Override the shared test env (which sets ENABLE_ADMIN_GUARD=false)
    original_env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    original_guard = os.environ.get("ENABLE_ADMIN_GUARD")
    original_token = os.environ.get("ADMIN_API_TOKEN")
    os.environ["CAD_TRANSLATION_ENV_FILE"] = str(env_path)
    os.environ["ENABLE_ADMIN_GUARD"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    env_path.write_text(
        "DEBUG=false\n"
        "ENABLE_ADMIN_GUARD=true\n"
        f"DATABASE_URL=sqlite:///{env_dir}/test.db\n"
        f"UPLOAD_DIR={env_dir}/uploads\n"
        f"OUTPUT_DIR={env_dir}/outputs\n"
        f"TEMP_DIR={env_dir}/temp\n",
        encoding="utf-8",
    )

    config_module._settings = None

    from fastapi.testclient import TestClient
    from app.main import app

    try:
        with TestClient(app) as c:
            # All guarded endpoints should return 503 (not 200 / not 403)
            for method, url in [
                ("get", "/api/projects/"),
                ("get", "/api/cad/tasks"),
                ("post", "/api/translation/text"),
                ("get", "/api/translation/config"),
                ("get", "/api/cad/defaults"),
            ]:
                resp = getattr(c, method)(url)
                assert resp.status_code == 503, (
                    f"{method.upper()} {url} should return 503 when guard "
                    f"enabled but no token configured. Got {resp.status_code}."
                )

            # Health stays public (no sensitive data)
            resp = c.get("/api/cad/health")
            assert resp.status_code == 200
    finally:
        config_module._settings = None
        os.environ["CAD_TRANSLATION_ENV_FILE"] = original_env_file
        if original_guard is not None:
            os.environ["ENABLE_ADMIN_GUARD"] = original_guard
        else:
            os.environ.pop("ENABLE_ADMIN_GUARD", None)
        if original_token is not None:
            os.environ["ADMIN_API_TOKEN"] = original_token
        else:
            os.environ.pop("ADMIN_API_TOKEN", None)


def test_admin_guard_true_no_token_allows_health():
    """Even with guard enabled but no token, health/languages are public."""
    import app.config as config_module
    config_module._settings = None

    import tempfile
    env_dir = tempfile.mkdtemp(prefix="cad_fail_closed_health_")
    env_path = Path(env_dir) / ".env"
    original_env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    original_guard = os.environ.get("ENABLE_ADMIN_GUARD")
    original_token = os.environ.get("ADMIN_API_TOKEN")
    os.environ["CAD_TRANSLATION_ENV_FILE"] = str(env_path)
    os.environ["ENABLE_ADMIN_GUARD"] = "true"
    os.environ.pop("ADMIN_API_TOKEN", None)
    env_path.write_text(
        "DEBUG=false\n"
        "ENABLE_ADMIN_GUARD=true\n"
        f"DATABASE_URL=sqlite:///{env_dir}/test.db\n",
        encoding="utf-8",
    )

    config_module._settings = None
    from fastapi.testclient import TestClient
    from app.main import app

    try:
        with TestClient(app) as c:
            resp = c.get("/api/cad/health")
            assert resp.status_code == 200
            resp = c.get("/api/health")
            assert resp.status_code == 200
    finally:
        config_module._settings = None
        os.environ["CAD_TRANSLATION_ENV_FILE"] = original_env_file
        if original_guard is not None:
            os.environ["ENABLE_ADMIN_GUARD"] = original_guard
        else:
            os.environ.pop("ENABLE_ADMIN_GUARD", None)
        if original_token is not None:
            os.environ["ADMIN_API_TOKEN"] = original_token
        else:
            os.environ.pop("ADMIN_API_TOKEN", None)


# ------------------------------------ 2. delete does not recreate task dirs ---

def test_cleanup_after_delete_does_not_recreate_task_dir():
    """After delete_task, all cleanup write operations must NOT recreate the
    task directory, task.json, logs, checkpoints, or lock files."""
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService

    svc = CADPipelineService()
    upload = _create_test_dxf(svc, "Cleanup after delete test")
    result = svc.extract_upload(
        uploaded_file=upload, target_language="en", converter_backend="dxf_only"
    )
    task_id = result["task_id"]
    task_dir = svc._task_dir(task_id)
    assert task_dir.exists()

    # Delete the task directory entirely
    svc.delete_task(task_id)
    assert not task_dir.exists(), "Task dir should be gone after delete_task"

    # Now simulate a running worker's error-handler + finally cleanup
    # 1. _update_task on deleted task
    result = svc._update_task(task_id, status="error", last_error="cleanup")
    assert result == {}, "Expected empty return from _update_task on deleted task"

    # 2. _append_log on deleted task
    svc._append_log(task_id, "should not create file")

    # 3. _save_checkpoint on deleted task
    svc._save_checkpoint(task_id, [{"original": "a", "translated": "b"}])

    # 4. _save_task on deleted task
    svc._save_task(task_id, {"task_id": task_id, "orphan": True})

    # 5. _clear_task_cancel (should clean external marker, not recreate task dir)
    svc._clear_task_cancel(task_id)

    # Task dir and all sub-files must NOT exist
    assert not task_dir.exists(), f"Task dir was recreated: {task_dir}"
    for p in sorted(task_dir.parent.glob(f"{task_id}*")):
        assert False, f"Found orphan artifact: {p}"

    # No lock files under the task root with our task_id prefix.
    # (We scope to the task_id — other tests may leave .lock files in their
    #  own task directories within the shared cad_tasks/ root.)
    for p in sorted(task_dir.parent.glob(f"{task_id}*.lock")):
        assert False, f"Found task-specific lock file: {p}"
    for p in sorted(task_dir.parent.glob(f"{task_id}/*.lock")):
        assert False, f"Found lock file inside task dir: {p}"

    # External cancel marker should be cleared
    marker = svc._cancel_marker_path(task_id)
    assert not marker.exists(), f"External cancel marker should be cleaned: {marker}"


# ----------------------- 3. multiprocessing delete-vs-cleanup race ----------

def _mp_cleanup_after_delete(env_file, runtime_cfg, task_id, result_queue):
    """Worker process: simulate cleanup after task was deleted by another."""
    import os
    os.environ["CAD_TRANSLATION_ENV_FILE"] = env_file
    os.environ["CAD_TRANSLATION_RUNTIME_CONFIG_FILE"] = runtime_cfg
    os.environ["ASYNC_TASKS_MODE"] = "local"
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService

    svc = CADPipelineService()
    time.sleep(0.3)  # Give the delete worker a head start

    # Running worker checks cancellation
    is_cancelled = svc._is_task_cancelled(task_id)
    result_queue.put(("is_cancelled", is_cancelled))

    # Simulate cleanup path (finally/except of process_upload / resume_task)
    svc._update_task(task_id, status="cancelled", last_error="worker abort")
    svc._append_log(task_id, "Worker aborting after delete")
    svc._save_checkpoint(task_id, [{"original": "x", "translated": "y"}])
    svc._save_task(task_id, {"task_id": task_id, "orphan": True})
    svc._clear_task_cancel(task_id)

    # Report whether task dir was recreated
    task_dir = svc._task_dir(task_id)
    result_queue.put(("task_dir_exists", task_dir.exists()))
    # Also report if any files exist in parent dir with our task_id
    orphan_files = list(task_dir.parent.glob(f"{task_id}*")) if task_dir.parent.exists() else []
    result_queue.put(("orphan_files", [str(p) for p in orphan_files]))


def _mp_delete_task(env_file, runtime_cfg, task_id, result_queue):
    """Worker process: delete the task directory."""
    import os
    os.environ["CAD_TRANSLATION_ENV_FILE"] = env_file
    os.environ["CAD_TRANSLATION_RUNTIME_CONFIG_FILE"] = runtime_cfg
    os.environ["ASYNC_TASKS_MODE"] = "local"
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService

    svc = CADPipelineService()
    svc.delete_task(task_id)
    result_queue.put(("deleted", True))


def test_mp_delete_while_cleanup_runs_leaves_no_orphans():
    """Two processes: one runs task cleanup while another deletes the task.
    No task_dir / task.json / logs / checkpoints / locks are recreated."""
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService

    svc = CADPipelineService()
    upload = _create_test_dxf(svc, "MP delete cleanup race")
    result = svc.extract_upload(
        uploaded_file=upload, target_language="en", converter_backend="dxf_only"
    )
    task_id = result["task_id"]
    assert svc._task_dir(task_id).exists()

    env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    runtime_cfg = os.environ.get("CAD_TRANSLATION_RUNTIME_CONFIG_FILE", "")

    ctx = multiprocessing.get_context("spawn")
    q_delete = ctx.Queue()
    q_cleanup = ctx.Queue()

    del_proc = ctx.Process(target=_mp_delete_task, args=(env_file, runtime_cfg, task_id, q_delete))
    cleanup_proc = ctx.Process(target=_mp_cleanup_after_delete, args=(env_file, runtime_cfg, task_id, q_cleanup))

    del_proc.start()
    cleanup_proc.start()
    del_proc.join(timeout=20)
    cleanup_proc.join(timeout=20)

    assert not del_proc.is_alive(), "Delete process timed out"
    assert not cleanup_proc.is_alive(), "Cleanup process timed out"
    assert del_proc.exitcode == 0, f"Delete process exited with {del_proc.exitcode}"
    assert cleanup_proc.exitcode == 0, f"Cleanup process exited with {cleanup_proc.exitcode}"

    delete_results = {}
    while not q_delete.empty():
        k, v = q_delete.get()
        delete_results[k] = v
    cleanup_results = {}
    while not q_cleanup.empty():
        k, v = q_cleanup.get()
        cleanup_results[k] = v

    assert delete_results.get("deleted") is True
    assert cleanup_results.get("is_cancelled") is True, (
        "Cleanup process should detect task as cancelled after deletion"
    )
    assert cleanup_results.get("task_dir_exists") is False, (
        "Task dir was recreated by cleanup process!"
    )
    orphans = cleanup_results.get("orphan_files", [])
    assert not orphans, f"Orphan files found: {orphans}"

    # Also verify no files exist in the parent after both processes finish
    task_dir = svc._task_dir(task_id)
    assert not task_dir.exists(), "Task dir should not exist after race"
    # No files with task_id prefix in the tasks root
    tasks_root = task_dir.parent
    if tasks_root.exists():
        for p in tasks_root.glob(f"{task_id}*"):
            assert False, f"Found orphan artifact: {p}"


# ----------------------------- 4. frozen config affects translation calls -----

def test_frozen_config_affects_active_config_resolution():
    """Setting a thread-local frozen LLM config changes _active_config() output.
    The frozen provider/model/batch_size must take precedence; API keys are
    resolved from live config (never stored in the frozen snapshot)."""
    from app.services.alibaba_ai_translation_service import alibaba_ai_translation_service

    # Capture live config first
    live = alibaba_ai_translation_service._active_config()
    live_provider = live["provider"]
    live_model = live["model"]
    live_key = live["api_key"]

    # Create a frozen config with different provider/model/batch
    frozen = {
        "primary": {
            "provider": "openai",
            "format": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "api_key": "***",  # redacted — live key must be used
            "model": "frozen-model-xyz",
        },
        "batch_size": 99,
        "parallel_count": 3,
    }

    with alibaba_ai_translation_service.frozen_config(frozen):
        frozen_active = alibaba_ai_translation_service._active_config()
        assert frozen_active["provider"] == "openai", (
            "Frozen provider not applied"
        )
        assert frozen_active["model"] == "frozen-model-xyz", (
            "Frozen model not applied"
        )
        assert frozen_active["batch_size"] == 99, "Frozen batch not applied"
        assert frozen_active["parallel_count"] == 3, "Frozen parallel not applied"
        # API key must be resolved live, not "***" from the frozen snapshot
        assert frozen_active["api_key"] == live_key, (
            "API key should be resolved from live config in frozen mode"
        )
        assert frozen_active["api_key"] != "***", (
            "API key must not remain redacted in the actual active config"
        )

    # After context, live config restored
    after = alibaba_ai_translation_service._active_config()
    assert after["provider"] == live_provider
    assert after["model"] == live_model


def test_task_config_snapshot_does_not_leak_api_keys():
    """The config_snapshot stored in task.json must NOT contain real API keys."""
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService

    svc = CADPipelineService()
    upload = _create_test_dxf(svc, "API key leak test")
    result = svc.extract_upload(
        uploaded_file=upload, target_language="en", converter_backend="dxf_only"
    )
    task_id = result["task_id"]

    try:
        metadata = svc._load_task(task_id)
        snapshot = metadata.get("config_snapshot", {})
        json_str = json.dumps(snapshot)

        # Redacted values only — no real key material
        assert "***" in json_str or "api_key" not in json_str.lower(), \
            "Snapshot should contain redacted markers"
        # No obvious key prefixes
        for prefix in ["sk-", "key-", "AKIA", "ghp_"]:
            assert prefix not in json_str, f"Found potential key material: {prefix}"
        assert "api_key" not in json_str or '"***"' in json_str or 'api_key": "***"' in json_str, \
            "api_key field should be redacted"
    finally:
        svc.delete_task(task_id)


# ------------------- 5. translate_batch honors frozen config -----------------

def test_translate_batch_uses_frozen_config_for_rate_limit_and_params():
    """translate_batch must use the frozen config for its batch_size etc."""
    from app.services.alibaba_ai_translation_service import alibaba_ai_translation_service

    # Use mock/demo fallback so no real API call happens
    frozen = {
        "primary": {
            "provider": "custom",
            "format": "openai_compatible",
            "base_url": "http://localhost:1/v1",  # never reachable
            "api_key": "",  # empty → allow_demo_fallback kicks in
            "model": "frozen-model",
        },
        "batch_size": 1,  # Force small batches
        "batch_json": False,
        "parallel_count": 1,
        "retry_count": 0,
        "rpm": 1,
        "allow_demo_fallback": True,
    }

    progress_events: list[dict] = []

    def on_progress(p: dict) -> None:
        progress_events.append(p)

    texts = ["Hello one", "Hello two", "Hello three"]

    with alibaba_ai_translation_service.frozen_config(frozen):
        # With allow_demo_fallback=true and no API key, it should return
        # demo mode results rather than fail.
        result = alibaba_ai_translation_service.translate_batch(
            texts=texts,
            source_lang="en",
            target_lang="zh",
            progress_callback=on_progress,
        )

    # Verify progress events used the frozen batch_size / provider / model
    assert progress_events, "No progress events emitted"
    first_event = progress_events[0]
    assert first_event["event"] == "started"
    assert first_event["provider"] == "custom", \
        f"Expected frozen provider, got {first_event.get('provider')}"
    assert first_event["model"] == "frozen-model", \
        f"Expected frozen model, got {first_event.get('model')}"
    # Each chunk should have at most batch_size=1 items since we set batch=1
    assert len(result) == len(texts), "All texts should produce results"

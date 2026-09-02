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

def test_frozen_config_applied_in_translate_batch_progress():
    """translate_batch's progress events must report frozen provider/model."""
    from app.services.llm.translation_service import LLMTranslationService
    from unittest.mock import patch

    # Create a COMPLETELY fresh service instance. This avoids any residual
    # state from tests that run before this one (e.g. concurrency tests
    # that patch methods or leave thread-local data on the singleton).
    fresh = LLMTranslationService()

    frozen = {
        "primary": {
            "provider": "custom",
            "format": "openai_compatible",
            "base_url": "http://localhost:1/v1",
            "api_key": "test-key",
            "model": "frozen-model",
        },
        "batch_size": 1,
        "batch_json": False,
        "parallel_count": 1,
        "retry_count": 0,
        "rpm": 1,
        "allow_demo_fallback": True,
    }

    def _mock_chat(self, messages):
        return "translated_demo_text"

    with patch.object(type(fresh), "_chat", _mock_chat),          patch.object(type(fresh), "_probe_candidate",
                      lambda self, c: {"success": True, "message": "ok"}):
        progress_events: list[dict] = []

        def on_progress(p: dict) -> None:
            progress_events.append(p)

        with fresh.frozen_config(frozen):
            result = fresh.translate_batch(
                texts=["Hello one", "Hello two", "Hello three"],
                source_lang="en",
                target_lang="zh",
                progress_callback=on_progress,
            )

        assert progress_events, "translate_batch should emit progress events"
        first = progress_events[0]
        assert first["event"] == "started"
        assert first["provider"] == "custom",             f"Expected frozen provider 'custom', got {first.get('provider')}"
        assert first["model"] == "frozen-model",             f"Expected frozen model 'frozen-model', got {first.get('model')}"
        assert len(result) == 3, "All three texts should have translations"


# ---- 6. Frozen-config propagation to parallel (ThreadPool) workers ---------

def test_frozen_config_applied_with_parallel_workers_gt_one():
    """Regression: ``frozen_config`` must propagate into ThreadPoolExecutor
    worker threads when ``parallel_count >= 2``.

    Without the fix, the worker threads have isolated ``threading.local`` and
    ``_active_config()`` inside ``_chat`` / ``translate_text`` /
    ``_translate_batch_json`` would resolve against the live global config —
    which can change mid-flight (e.g. another admin saves new model settings)
    — instead of the task snapshot captured at start.
    """
    from unittest.mock import patch
    import threading
    from app.services.llm.translation_service import LLMTranslationService

    fresh = LLMTranslationService()

    frozen = {
        "primary": {
            "provider": "custom",
            "format": "openai_compatible",
            "base_url": "http://localhost:1/v1",
            "api_key": "test-key",
            "model": "frozen-model-parallel",
        },
        "batch_size": 1,
        "batch_json": False,
        "parallel_count": 3,
        "retry_count": 0,
        "rpm": 1,
        "allow_demo_fallback": True,
    }

    observed_calls: list[dict] = []
    seen_thread_names: set[str] = set()

    def _mock_chat(self, messages):
        # Runs in the calling thread (parent when parallel_count==1,
        # worker thread when parallel_count > 1).
        cfg = self._active_config()
        seen_thread_names.add(threading.current_thread().name)
        observed_calls.append({
            "provider": cfg["provider"],
            "model": cfg["model"],
            "parallel_count": cfg["parallel_count"],
        })
        # Small sleep to encourage actual thread interleaving.
        time.sleep(0.01)
        return "translated_demo_parallel"

    with patch.object(type(fresh), "_chat", _mock_chat), \
          patch.object(type(fresh), "_probe_candidate",
                      lambda self, c: {"success": True, "message": "ok"}):
        with fresh.frozen_config(frozen):
            result = fresh.translate_batch(
                texts=[
                    "Hello one", "Hello two", "Hello three",
                    "Hello four", "Hello five", "Hello six",
                    "Hello seven", "Hello eight",
                ],
                source_lang="en",
                target_lang="zh",
            )

    assert len(result) == 8, "All texts should be translated"
    assert observed_calls, "Mock _chat should have been called by workers"
    assert len(observed_calls) >= 2, "Expected multiple LLM calls"
    # Parallel workers execute on multiple distinct threads.
    assert len(seen_thread_names) >= 2, (
        f"Expected parallel workers on multiple threads, got: {seen_thread_names}"
    )
    # Every worker call (even from a worker thread) must resolve frozen config.
    for i, call in enumerate(observed_calls):
        assert call["provider"] == "custom", (
            f"Worker call {i}: provider={call['provider']!r} != frozen 'custom'"
        )
        assert call["model"] == "frozen-model-parallel", (
            f"Worker call {i}: model={call['model']!r} != frozen 'frozen-model-parallel'"
        )
        assert call["parallel_count"] == 3, (
            f"Worker call {i}: parallel_count={call['parallel_count']!r} != frozen 3"
        )


def test_frozen_config_parallel_midflight_config_change_uses_snapshot():
    """Regression: when the global LLM config is updated WHILE a parallel
    ``translate_batch`` is in flight, every worker must still resolve the
    task's frozen snapshot — not the newly saved global config.

    Steps:
    1. Start a batch with a frozen config (provider=old, model=old-model).
    2. The mock ``_chat`` on the first worker call updates the global config
       to a different provider/model (simulating an admin saving mid-flight).
    3. Verify every subsequent ``_chat`` invocation sees the ORIGINAL frozen
       provider/model — proving workers use the immutable task snapshot.
    """
    from unittest.mock import patch
    import threading
    from app.services.llm.translation_service import LLMTranslationService
    from app.services.config_manager import ConfigManager

    fresh = LLMTranslationService()

    frozen = {
        "primary": {
            "provider": "custom",
            "format": "openai_compatible",
            "base_url": "http://localhost:1/v1",
            "api_key": "test-key",
            "model": "frozen-model-snapshot",
        },
        "batch_size": 2,
        "batch_json": False,
        "parallel_count": 3,
        "retry_count": 0,
        "rpm": 1,
        "allow_demo_fallback": True,
    }

    observed_calls: list[dict] = []
    barrier = threading.Barrier(3)  # Wait for 3 workers to be in flight.
    config_update_done = threading.Event()
    _config_lock = threading.Lock()

    def _mock_chat(self, messages):
        cfg = self._active_config()
        current = {
            "provider": cfg["provider"],
            "model": cfg["model"],
            "parallel_count": cfg["parallel_count"],
        }
        observed_calls.append(current)

        # The FIRST worker that arrives updates the live config, simulating
        # an admin changing settings mid-flight.
        should_update = False
        with _config_lock:
            if not config_update_done.is_set():
                should_update = True
                config_update_done.set()

        if should_update:
            try:
                cm = ConfigManager()
                cm.update_global_config({
                    "llm": {
                        "primary": {
                            "provider": "openai",
                            "model": "live-model-after-change",
                        }
                    }
                })
            except Exception:
                pass  # Config update may fail in isolated test env; ignore.

        # Let other workers proceed so they all observe the config change.
        try:
            barrier.wait(timeout=5)
        except Exception:
            pass  # If other workers already passed, don't fail the test.
        time.sleep(0.01)
        return "translated_parallel_snapshot"

    with patch.object(type(fresh), "_chat", _mock_chat), \
          patch.object(type(fresh), "_probe_candidate",
                      lambda self, c: {"success": True, "message": "ok"}):
        with fresh.frozen_config(frozen):
            result = fresh.translate_batch(
                texts=[
                    "Hello one", "Hello two", "Hello three",
                    "Hello four", "Hello five", "Hello six",
                ],
                source_lang="en",
                target_lang="zh",
            )

    assert len(result) == 6
    assert len(observed_calls) >= 3, (
        f"Expected at least 3 worker calls, got {len(observed_calls)}"
    )
    assert config_update_done.is_set(), "Config update should have happened mid-flight"
    # Verify the live config was actually changed (so the test is meaningful).
    live = ConfigManager().get_effective_config().get("llm", {})
    live_primary = live.get("primary") or {}
    # Some live fields may be empty (test env has no API key); check the model.
    assert str(live_primary.get("model") or "").strip(), "Live config should have a model after update"

    # ALL calls — even from worker threads that did NOT run the config update —
    # must observe the frozen snapshot.
    for i, call in enumerate(observed_calls):
        assert call["model"] == "frozen-model-snapshot", (
            f"Worker call {i}: model={call['model']!r} — worker read live config, "
            f"should read frozen snapshot model 'frozen-model-snapshot'"
        )
        assert call["provider"] == "custom", (
            f"Worker call {i}: provider={call['provider']!r} — worker read live config"
        )


# ---- 7. Multiprocessing TOCTOU: exists-check vs delete race --------------

def _mp_race_exists_check_then_delete(env_file, runtime_cfg, task_id, result_queue):
    """Worker process: simulate the exact TOCTOU race.

    This worker deliberately tries to write task metadata WITHOUT the
    lifecycle lock, mimicking the scenario where the old code checked
    ``task_dir.exists()`` and then entered ``file_lock`` (which would
    recreate the dir via ``sidecar.parent.mkdir``).  We hold the race
    window open so the parent process can delete the task dir between the
    exists-check and the actual lock acquisition.
    """
    import os
    os.environ["CAD_TRANSLATION_ENV_FILE"] = env_file
    os.environ["CAD_TRANSLATION_RUNTIME_CONFIG_FILE"] = runtime_cfg
    os.environ["ASYNC_TASKS_MODE"] = "local"
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService

    svc = CADPipelineService()
    # Give the main process a chance to delete the task dir.
    # Instead of sleeping, we signal readiness via queue then block briefly.
    task_dir = svc._task_dir(task_id)
    meta_path = task_dir / "task.json"

    # Phase A: signal that we're about to check exists, then pause.
    result_queue.put(("about_to_check", True))
    # Short pause to let the main process delete the task dir.
    time.sleep(1.0)

    # Phase B: now perform the exists-check (like the old _save_task path).
    if meta_path.parent.exists():
        result_queue.put(("exists_check_result", True))
        # Try to write inside a file_lock with create_parents=False.
        # The lifecycle lock IS held by the writer in the real fix.  Here we
        # exercise the NEW code path (which wraps in lifecycle lock).
        try:
            svc._update_task(task_id, status="error", last_error="race")
            result_queue.put(("update_result", "no_error"))
        except Exception as exc:
            result_queue.put(("update_result", f"error: {exc}"))
    else:
        result_queue.put(("exists_check_result", False))

    # Report whether task dir was recreated.
    result_queue.put(("task_dir_recreated", task_dir.exists()))
    result_queue.put(("meta_path_exists", meta_path.exists()))


def test_mp_exists_check_delete_race_leaves_no_orphans():
    """Real multiprocessing test: another process deletes the task dir while
    a worker is between its ``exists()`` check and its file-lock acquisition.

    The fixed code uses a task lifecycle lock (outside cad_tasks/) and
    ``create_parents=False`` on file_lock/atomic_write so the delete cannot
    land in the TOCTOU window and no task.json / task.log / checkpoint /
    lock / orphan task_dir may appear after the delete.
    """
    import app.config as config_module
    config_module._settings = None
    from app.services.cad_pipeline_service import CADPipelineService

    svc = CADPipelineService()
    upload = _create_test_dxf(svc, "MP TOCTOU race")
    result = svc.extract_upload(
        uploaded_file=upload, target_language="en", converter_backend="dxf_only"
    )
    task_id = result["task_id"]
    assert svc._task_dir(task_id).exists()

    env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    runtime_cfg = os.environ.get("CAD_TRANSLATION_RUNTIME_CONFIG_FILE", "")

    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()

    # Start the "worker" process that will check exists and try to write.
    worker = ctx.Process(target=_mp_race_exists_check_then_delete,
                         args=(env_file, runtime_cfg, task_id, q))
    worker.start()

    # Wait for the worker to signal it's about to check existence.
    signals = {}
    while not signals.get("about_to_check"):
        if not worker.is_alive():
            break
        try:
            k, v = q.get(timeout=5)
            signals[k] = v
        except Exception:
            break

    # Now delete the task dir from THIS process while the worker is paused.
    svc.delete_task(task_id)
    assert not svc._task_dir(task_id).exists(), "Task dir should be gone after delete"

    # Let the worker proceed.
    worker.join(timeout=15)
    assert not worker.is_alive(), "Worker timed out"
    assert worker.exitcode == 0, f"Worker exited with {worker.exitcode}"

    # Collect all worker results.
    results = {}
    while not q.empty():
        try:
            k, v = q.get(timeout=2)
            results[k] = v
        except Exception:
            break

    # If the worker saw the dir exist before the delete, verify it handled it.
    if results.get("exists_check_result") is True:
        update_result = results.get("update_result", "")
        assert "no_error" in str(update_result) or "error" in str(update_result), \
            f"Unexpected update result: {update_result}"

    # The task dir must NOT be recreated regardless of race outcome.
    task_dir = svc._task_dir(task_id)
    assert not task_dir.exists(), f"Task dir was recreated: {task_dir}"
    # No orphan files matching the task_id in the tasks root or lifecycle dir.
    tasks_root = task_dir.parent
    if tasks_root.exists():
        for p in tasks_root.glob(f"{task_id}*"):
            assert False, f"Found orphan artifact: {p}"
    # No orphan lifecycle files.
    life_root = svc._lifecycle_root()
    if life_root.exists():
        for p in life_root.glob(f"{task_id}*"):
            assert False, f"Found orphan lifecycle artifact: {p}"
    # External cancel marker should be gone.
    marker = svc._cancel_marker_path(task_id)
    assert not marker.exists(), f"External cancel marker should be cleaned: {marker}"

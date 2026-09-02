#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for CAD pipeline concurrency: parallel task isolation, file locking,
and metadata integrity when multiple tasks run simultaneously.

Run: python -m pytest tests/backend/test_cad_pipeline_concurrency.py -v
"""

import io
import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import UploadFile


@pytest.fixture
def upload_files(fixtures_dir):
    """Build three UploadFile objects from the DXF fixtures."""

    def _build(name: str) -> UploadFile:
        path = fixtures_dir / f"{name}.dxf"
        data = path.read_bytes()
        return UploadFile(
            filename=f"{name}.dxf",
            file=io.BytesIO(data),
        )

    return {
        "building_a": _build("building_a"),
        "building_b": _build("building_b"),
        "building_c": _build("building_c"),
    }


@pytest.fixture
def pipeline_service():
    """Get the global CADPipelineService with clean state."""
    from app.services.cad_pipeline_service import cad_pipeline_service

    # Clear any existing tasks
    cad_pipeline_service.clear_all_tasks()
    return cad_pipeline_service


def test_single_dxf_pipeline_extract_only(pipeline_service, upload_files):
    """Test a single DXF upload with extract_only=True."""
    file = upload_files["building_a"]
    result = pipeline_service.extract_upload(
        uploaded_file=file,
        target_language="en",
        converter_backend="dxf_only",
    )

    assert result["task_id"]
    assert result["text_count"] == 3
    assert result["excel_file_url"]
    assert len(result["texts"]) == 3

    # Verify task metadata is correct
    metadata = pipeline_service._load_task(result["task_id"])
    assert metadata["original_filename"] == "building_a.dxf"
    assert metadata["text_count"] == 3
    assert metadata["status"] == "processing"
    assert metadata["stage"] == "extracting"


def test_three_parallel_tasks_isolation(pipeline_service, upload_files):
    """Test that 3 parallel DXF tasks produce isolated outputs with no cross-contamination."""
    from concurrent.futures import ThreadPoolExecutor

    results = {}

    def _process(name: str, file) -> dict:
        r = pipeline_service.extract_upload(
            uploaded_file=file,
            target_language="en",
            converter_backend="dxf_only",
        )
        results[name] = r
        return r

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(_process, "building_a", upload_files["building_a"]),
            executor.submit(_process, "building_b", upload_files["building_b"]),
            executor.submit(_process, "building_c", upload_files["building_c"]),
        ]
        for f in futures:
            f.result(timeout=30)

    # All three tasks succeeded
    assert set(results.keys()) == {"building_a", "building_b", "building_c"}
    for name, r in results.items():
        assert r["task_id"]
        assert r["text_count"] == 3

    # Task IDs must be unique
    task_ids = [r["task_id"] for r in results.values()]
    assert len(set(task_ids)) == 3, f"Task IDs should be unique, got: {task_ids}"

    # Each task has its own directory
    for name, r in results.items():
        task_dir = pipeline_service._task_dir(r["task_id"])
        assert task_dir.exists()
        assert (task_dir / "task.json").exists()

    # No task should have files from another task
    for name, r in results.items():
        metadata = pipeline_service._load_task(r["task_id"])
        assert metadata["original_filename"] == f"{name}.dxf"

    # All task dirs are separate
    task_dirs = {pipeline_service._task_dir(r["task_id"]) for r in results.values()}
    assert len(task_dirs) == 3


def test_parallel_task_metadata_updates_no_lost_updates(pipeline_service, upload_files):
    """Test that concurrent _update_task calls don't lose updates."""
    from concurrent.futures import ThreadPoolExecutor

    # Create one task
    result = pipeline_service.extract_upload(
        uploaded_file=upload_files["building_a"],
        target_language="en",
        converter_backend="dxf_only",
    )
    task_id = result["task_id"]

    # Fire many concurrent updates with different keys
    def _update(idx: int):
        key = f"field_{idx}"
        value = f"value_{idx}"
        pipeline_service._update_task(task_id, **{key: value})

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_update, i) for i in range(20)]
        for f in futures:
            f.result(timeout=10)

    metadata = pipeline_service._load_task(task_id)
    for i in range(20):
        assert metadata.get(f"field_{i}") == f"value_{i}", f"field_{i} was lost!"

    # Also verify that concurrent updates to the SAME key don't lose the last one
    def _update_status(value: str):
        pipeline_service._update_task(task_id, status=value)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_update_status, f"status_{i}") for i in range(5)]
        for f in futures:
            f.result(timeout=10)

    metadata = pipeline_service._load_task(task_id)
    assert metadata["status"] in {"status_0", "status_1", "status_2", "status_3", "status_4"}


def test_task_logs_are_isolated(pipeline_service, upload_files):
    """Test that task logs don't bleed between concurrent tasks."""
    from concurrent.futures import ThreadPoolExecutor

    results = {}

    def _process(name: str, file) -> str:
        r = pipeline_service.extract_upload(
            uploaded_file=file,
            target_language="en",
            converter_backend="dxf_only",
        )
        task_id = r["task_id"]
        # Write a unique marker to the log
        pipeline_service._append_log(task_id, f"UNIQUE_MARKER_{name}")
        results[name] = task_id
        return task_id

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(_process, "building_a", upload_files["building_a"]),
            executor.submit(_process, "building_b", upload_files["building_b"]),
            executor.submit(_process, "building_c", upload_files["building_c"]),
        ]
        for f in futures:
            f.result(timeout=30)

    for name, task_id in results.items():
        logs = pipeline_service.get_task_logs(task_id)
        assert f"UNIQUE_MARKER_{name}" in logs
        for other in ("building_a", "building_b", "building_c"):
            if other != name:
                assert f"UNIQUE_MARKER_{other}" not in logs


def test_full_pipeline_with_mock_translation(pipeline_service, upload_files):
    """Test the full pipeline (extract -> translate -> apply) with a mock LLM."""
    file = upload_files["building_a"]

    # Create a mock that translates any text to a fixed string
    def _mock_translate(texts, **kwargs):
        return [f"译文_{i}" for i in range(len(texts))]

    with patch(
        "app.services.alibaba_ai_translation_service.alibaba_ai_translation_service.translate_batch",
        side_effect=_mock_translate,
    ):
        result = pipeline_service.process_upload(
            uploaded_file=file,
            target_language="zh",
            converter_backend="dxf_only",
            extract_only=False,
            translation_mode="replace",
        )

    assert result["task_id"]
    assert result["translation_count"] == 3
    assert result["translated_cad_file"]
    assert result["status"] == "done"


def test_full_pipeline_parallel_mock_translation(pipeline_service, upload_files):
    """Test 3 full pipelines in parallel with a thread-local mock translation.

    The mock is designed to return per-thread deterministic translations so we
    can verify that each task gets its own translation set.
    """
    from concurrent.futures import ThreadPoolExecutor

    # Thread-local storage so each thread gets its own translation mapping
    _thread_local = threading.local()
    translations_by_name = {
        "building_a": ["主入口", "消防逃生楼梯", "暖通控制室"],
        "building_b": ["结构梁B1", "电梯井", "停车场层"],
        "building_c": ["发电机室", "安全检查站", "装卸码头"],
    }

    def _thread_mock_translate(texts, **kwargs):
        """Mock translate_batch that returns translations for the current thread's task."""
        name = getattr(_thread_local, "task_name", None)
        if name in translations_by_name:
            expected = translations_by_name[name]
            return expected[: len(texts)]
        # Default fallback
        return [f"T{t}" for t in texts]

    results = {}

    def _process(name: str, file) -> dict:
        # Set thread-local task name so the mock can distinguish tasks
        _thread_local.task_name = name
        with patch(
            "app.services.alibaba_ai_translation_service.alibaba_ai_translation_service.translate_batch",
            side_effect=_thread_mock_translate,
        ):
            r = pipeline_service.process_upload(
                uploaded_file=file,
                target_language="zh",
                converter_backend="dxf_only",
                extract_only=False,
                translation_mode="replace",
            )
        results[name] = r
        return r

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(_process, "building_a", upload_files["building_a"]),
            executor.submit(_process, "building_b", upload_files["building_b"]),
            executor.submit(_process, "building_c", upload_files["building_c"]),
        ]
        for f in futures:
            f.result(timeout=60)

    # All completed
    for name, r in results.items():
        assert r["task_id"]
        assert r["translation_count"] == 3
        assert r["status"] == "done"
        assert r["translated_cad_file"]

    # Task IDs are unique
    task_ids = [r["task_id"] for r in results.values()]
    assert len(set(task_ids)) == 3

    # Check translated CAD files exist and are isolated
    for name, r in results.items():
        metadata = pipeline_service._load_task(r["task_id"])
        task_dir = pipeline_service._task_dir(r["task_id"])
        translated_file = task_dir / metadata["translated_cad_filename"]
        assert translated_file.exists()

        # Read the DXF and verify the text was replaced correctly
        import ezdxf
        doc = ezdxf.readfile(str(translated_file))
        msp = doc.modelspace()
        texts = [e.dxf.text for e in msp if e.dxftype() in ("TEXT", "MTEXT")]
        expected = translations_by_name[name]
        for expected_text in expected:
            assert expected_text in texts, (
                f"Task {name} should contain '{expected_text}' but got texts: {texts}"
            )
        # Verify no cross-contamination
        for other in translations_by_name:
            if other != name:
                for other_text in translations_by_name[other]:
                    assert other_text not in texts, (
                        f"Task {name} should NOT contain '{other_text}' from {other}"
                    )


def test_concurrent_config_file_writes_are_safe():
    """Test that concurrent writes to the runtime config file don't corrupt it."""
    from app.services.runtime_config_service import runtime_config_service
    from concurrent.futures import ThreadPoolExecutor

    def _write_config(i: int):
        runtime_config_service.update_runtime_config(
            {
                "provider": "custom",
                "model": f"model-{i}",
                "batch_size": i + 1,
            }
        )

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_write_config, i) for i in range(10)]
        for f in futures:
            f.result(timeout=10)

    # Verify the config file is still valid JSON and not corrupted
    from app.config import load_runtime_config
    payload = load_runtime_config()
    assert isinstance(payload, dict)
    llm = payload.get("llm", {})
    assert "primary" in llm
    assert llm["primary"]["model"] in {f"model-{i}" for i in range(10)}
    # batch_size should be one of the written values
    assert llm["batch_size"] in {i + 1 for i in range(10)}


def test_download_path_isolation(pipeline_service, upload_files):
    """Test that download resolves paths correctly and doesn't leak across tasks."""
    from concurrent.futures import ThreadPoolExecutor

    task_ids = {}

    def _process(name: str, file) -> str:
        r = pipeline_service.extract_upload(
            uploaded_file=file,
            target_language="en",
            converter_backend="dxf_only",
        )
        task_ids[name] = r["task_id"]
        return r["task_id"]

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(_process, "building_a", upload_files["building_a"]),
            executor.submit(_process, "building_b", upload_files["building_b"]),
            executor.submit(_process, "building_c", upload_files["building_c"]),
        ]
        for f in futures:
            f.result(timeout=30)

    # Verify each task's Excel download resolves to its own file
    for name, task_id in task_ids.items():
        file_path, media_type = pipeline_service.resolve_download(task_id, "excel")
        assert file_path.exists()
        assert name in file_path.name

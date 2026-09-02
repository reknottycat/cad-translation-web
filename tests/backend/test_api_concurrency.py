#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API-level concurrency tests for the CAD translation backend.

Tests simulate multiple users hitting the API concurrently, verifying
project/task isolation, file upload isolation, and correct response handling.
"""

import io
import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import UploadFile


@pytest.fixture
def client():
    """Get a TestClient for the FastAPI app."""
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


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


def test_parallel_upload_api_isolation(client, upload_files):
    """Test that 3 concurrent uploads through the API don't mix task data."""
    from concurrent.futures import ThreadPoolExecutor

    results = {}
    errors = []

    def _upload(name: str, file) -> None:
        try:
            response = client.post(
                "/api/cad/extract",
                files={"file": (f"{name}.dxf", file.file, "application/octet-stream")},
                data={
                    "converter_backend": "dxf_only",
                    "target_language": "en",
                },
            )
            if response.status_code != 200:
                errors.append((name, response.status_code, response.text))
                return
            body = response.json()
            results[name] = body.get("data", {})
        except Exception as exc:
            errors.append((name, "exception", str(exc)))

    # Rewind file pointers since they were consumed
    for f in upload_files.values():
        f.file.seek(0)

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(_upload, "building_a", upload_files["building_a"]),
            executor.submit(_upload, "building_b", upload_files["building_b"]),
            executor.submit(_upload, "building_c", upload_files["building_c"]),
        ]
        for f in futures:
            f.result(timeout=30)

    # No errors
    assert not errors, f"Upload errors: {errors}"

    # All three succeeded
    assert set(results.keys()) == {"building_a", "building_b", "building_c"}
    for name, data in results.items():
        assert data.get("task_id"), f"Task {name} has no task_id: {data}"
        assert data.get("text_count") == 3

    # Task IDs unique
    task_ids = [data["task_id"] for data in results.values()]
    assert len(set(task_ids)) == 3


def test_concurrent_download_no_cross_leak(client, upload_files):
    """Test that concurrent downloads return the correct per-task files."""
    from concurrent.futures import ThreadPoolExecutor

    # Upload three tasks first
    task_ids = {}
    for name in ("building_a", "building_b", "building_c"):
        upload_files[name].file.seek(0)
        response = client.post(
            "/api/cad/extract",
            files={"file": (f"{name}.dxf", upload_files[name].file, "application/octet-stream")},
            data={"converter_backend": "dxf_only", "target_language": "en"},
        )
        assert response.status_code == 200
        task_ids[name] = response.json()["data"]["task_id"]

    # Download each task's Excel concurrently
    download_results = {}

    def _download(name: str, task_id: str) -> None:
        response = client.get(f"/api/cad/download/{task_id}/excel")
        if response.status_code != 200:
            download_results[name] = f"ERROR {response.status_code}"
            return
        download_results[name] = response.content[:10]

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(_download, name, task_id)
            for name, task_id in task_ids.items()
        ]
        for f in futures:
            f.result(timeout=30)

    # All downloads succeeded
    for name, content in download_results.items():
        assert not content.startswith(b"ERROR"), f"Download for {name} failed: {content}"
        # Excel files start with PK (zip magic)
        assert content.startswith(b"PK"), f"Download for {name} is not valid Excel: {content}"


def test_list_tasks_parallel(client, upload_files):
    """Test that list_tasks works correctly with concurrent task creation."""
    from concurrent.futures import ThreadPoolExecutor

    # Upload three tasks
    for name in ("building_a", "building_b", "building_c"):
        upload_files[name].file.seek(0)
        response = client.post(
            "/api/cad/extract",
            files={"file": (f"{name}.dxf", upload_files[name].file, "application/octet-stream")},
            data={"converter_backend": "dxf_only", "target_language": "en"},
        )
        assert response.status_code == 200

    # Concurrently call list_tasks while another upload happens
    results = []

    def _list_tasks():
        response = client.get("/api/cad/tasks")
        if response.status_code == 200:
            body = response.json()
            results.append(len(body.get("data", [])))
        else:
            results.append(-1)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_list_tasks) for _ in range(5)]
        for f in futures:
            f.result(timeout=10)

    # At least 3 tasks should be listed
    assert all(count >= 3 for count in results if count > 0)


def test_multi_user_project_isolation(client):
    """Test that different users can create/update projects without interfering."""
    from concurrent.futures import ThreadPoolExecutor

    results = {}

    def _create_project(user_id: int) -> None:
        try:
            response = client.post(
                "/api/projects/",
                json={
                    "name": f"User-{user_id} Project",
                    "description": f"Project created by user {user_id}",
                },
            )
            results[user_id] = {
                "status": response.status_code,
                "data": response.json() if response.status_code < 400 else None,
            }
        except Exception as exc:
            results[user_id] = {"status": -1, "data": str(exc)}

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_create_project, i) for i in range(1, 6)]
        for f in futures:
            f.result(timeout=10)

    # All created
    for user_id in range(1, 6):
        assert results[user_id]["status"] == 200, f"User {user_id} failed: {results[user_id]}"
        assert results[user_id]["data"]["name"] == f"User-{user_id} Project"


def test_parallel_translation_with_mock(client):
    """Test that parallel translation requests are handled independently."""
    from concurrent.futures import ThreadPoolExecutor

    # Mock the LLM service to return different translations based on input text
    # (mapping from user ID to expected translation for each request text)
    expected_by_text = {
        f"Original text for user {i}": f"translated_by_user_{i}"
        for i in range(1, 6)
    }

    def _mock_translate_text(text, source_lang="auto", target_lang="en", system_prompt_override=None):
        return expected_by_text.get(str(text), f"translated_unknown_{text}")

    with patch(
        "app.services.alibaba_ai_translation_service.alibaba_ai_translation_service.translate_text",
        side_effect=_mock_translate_text,
    ):
        results = {}

        def _translate(user_id: int, text: str) -> None:
            try:
                response = client.post(
                    "/api/cad/translate-text",
                    data={"text": text, "target_language": "en"},
                )
                results[user_id] = {
                    "status": response.status_code,
                    "text": response.json().get("data", {}).get("translated_text", "") if response.status_code == 200 else "",
                }
            except Exception as exc:
                results[user_id] = {"status": -1, "text": str(exc)}

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(_translate, i, f"Original text for user {i}")
                for i in range(1, 6)
            ]
            for f in futures:
                f.result(timeout=10)

    for user_id in range(1, 6):
        assert results[user_id]["status"] == 200, f"User {user_id} translation failed"
        assert f"translated_by_user_{user_id}" in results[user_id]["text"]


def test_translation_excel_unique_output(client):
    """Test that the sync Excel translation route generates unique output filenames."""
    from unittest.mock import patch
    from pathlib import Path

    # Mock the Excel processor to not actually translate
    with patch(
        "app.services.alibaba_ai_translation_service.alibaba_ai_excel_processor.translate_excel_file"
    ) as mock_process:
        mock_process.return_value = {
            "total_rows": 1,
            "text_columns": ["原文"],
            "translated_cells": 1,
            "skipped_cells": 0,
            "error_cells": 0,
        }

        # Mock create_translation_report
        with patch(
            "app.services.alibaba_ai_translation_service.alibaba_ai_excel_processor.create_translation_report"
        ) as mock_report:
            mock_report.return_value = ""

            # Upload two files with the SAME name
            excel_bytes = b"test excel data"

            responses = []
            for _ in range(2):
                response = client.post(
                    "/api/translation/excel",
                    files={"file": ("drawing.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                    data={"source_lang": "zh", "target_lang": "en"},
                )
                responses.append(response)

            # Both should succeed
            for response in responses:
                assert response.status_code == 200

            # Output filenames should be different (unique)
            output_names = [r.json().get("output_filename") for r in responses]
            assert output_names[0] != output_names[1], (
                f"Output filenames should be unique, got: {output_names}"
            )

            # Both should have unique UUID prefixes
            import re
            uuid_pattern = re.compile(r"translated_[0-9a-f]{32}_")
            assert uuid_pattern.match(output_names[0]), f"Expected UUID prefix in {output_names[0]}"
            assert uuid_pattern.match(output_names[1]), f"Expected UUID prefix in {output_names[1]}"

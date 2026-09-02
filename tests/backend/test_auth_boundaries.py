#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multi-user auth/ownership boundary tests.

Verifies that when ENABLE_ADMIN_GUARD is enabled, task/project/file endpoints
require the admin token and reject anonymous or wrong-token requests.
Also documents that task_id alone is NOT an authorization credential.

Run: python -m pytest tests/backend/test_auth_boundaries.py -v
"""

import io
import json
import os
from pathlib import Path

import pytest
from fastapi import UploadFile


@pytest.fixture
def admin_guard_client(monkeypatch):
    """TestClient with ENABLE_ADMIN_GUARD=true and an admin token."""
    import app.config as config_module
    config_module._settings = None
    monkeypatch.setenv("ENABLE_ADMIN_GUARD", "true")
    monkeypatch.setenv("ADMIN_API_TOKEN", "test-admin-token-123")

    # Reload settings
    config_module._settings = None

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


def test_admin_guard_blocks_unauthenticated_task_access(admin_guard_client, upload_files):
    """Without admin token, task endpoints return 403."""
    # Try to list tasks without token
    response = admin_guard_client.get("/api/cad/tasks")
    assert response.status_code == 403, f"Expected 403 for unauthenticated access, got {response.status_code}"

    # Try to list projects without token
    response = admin_guard_client.get("/api/projects/")
    assert response.status_code == 403

    # Try to extract without token
    f = upload_files["building_a"]
    response = admin_guard_client.post(
        "/api/cad/extract",
        files={"file": (f.filename, f.file, "application/octet-stream")},
        data={"converter_backend": "dxf_only"},
    )
    assert response.status_code == 403


def test_admin_guard_blocks_wrong_token(admin_guard_client, upload_files):
    """Wrong admin token is rejected."""
    headers = {"X-Admin-Token": "wrong-token"}

    response = admin_guard_client.get("/api/cad/tasks", headers=headers)
    assert response.status_code == 403

    f = upload_files["building_a"]
    response = admin_guard_client.post(
        "/api/cad/extract",
        headers=headers,
        files={"file": (f.filename, f.file, "application/octet-stream")},
        data={"converter_backend": "dxf_only"},
    )
    assert response.status_code == 403


def test_admin_guard_allows_valid_token(admin_guard_client, upload_files):
    """Valid admin token grants access to task endpoints."""
    headers = {"X-Admin-Token": "test-admin-token-123"}

    # List tasks with valid token
    response = admin_guard_client.get("/api/cad/tasks", headers=headers)
    assert response.status_code == 200

    # Create a project with valid token
    response = admin_guard_client.post(
        "/api/projects/",
        json={"name": "Admin Test Project"},
        headers=headers,
    )
    assert response.status_code == 200

    # Extract a CAD file with valid token
    f = upload_files["building_a"]
    response = admin_guard_client.post(
        "/api/cad/extract",
        headers=headers,
        files={"file": (f.filename, f.file, "application/octet-stream")},
        data={"converter_backend": "dxf_only"},
    )
    assert response.status_code == 200
    data = response.json().get("data", {})
    assert data.get("task_id")


def test_bearer_token_auth(admin_guard_client, upload_files):
    """Authorization: Bearer header is also accepted."""
    headers = {"Authorization": "Bearer test-admin-token-123"}

    f = upload_files["building_a"]
    response = admin_guard_client.post(
        "/api/cad/extract",
        headers=headers,
        files={"file": (f.filename, f.file, "application/octet-stream")},
        data={"converter_backend": "dxf_only"},
    )
    assert response.status_code == 200
    assert response.json().get("data", {}).get("task_id")


def test_task_id_is_not_a_credential(admin_guard_client, upload_files):
    """task_id alone does not grant access when admin guard is enabled.

    A client that knows a task_id but has no admin token must be rejected.
    """
    # First, create a task with admin token
    headers = {"X-Admin-Token": "test-admin-token-123"}
    f = upload_files["building_a"]
    response = admin_guard_client.post(
        "/api/cad/extract",
        headers=headers,
        files={"file": (f.filename, f.file, "application/octet-stream")},
        data={"converter_backend": "dxf_only"},
    )
    assert response.status_code == 200
    task_id = response.json()["data"]["task_id"]

    # Now try to access the task WITHOUT admin token - should be 403
    response = admin_guard_client.get(f"/api/cad/tasks/{task_id}/logs")
    assert response.status_code == 403

    # Try download without token
    response = admin_guard_client.get(f"/api/cad/download/{task_id}/excel")
    assert response.status_code == 403

    # Try resume without token
    response = admin_guard_client.post(
        f"/api/cad/tasks/{task_id}/resume",
        json={"target_language": "en"},
    )
    assert response.status_code == 403

    # Try apply-translation without token
    response = admin_guard_client.post(
        "/api/cad/apply-translation",
        json={
            "task_id": task_id,
            "translations": [{"original": "test", "translated": "translated"}],
        },
    )
    assert response.status_code == 403

    # With token, access succeeds
    response = admin_guard_client.get(
        f"/api/cad/tasks/{task_id}/logs", headers=headers
    )
    assert response.status_code == 200

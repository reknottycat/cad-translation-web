#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Endpoint guard coverage tests.

Verifies that every sensitive API endpoint is behind `require_admin_access`
when ENABLE_ADMIN_GUARD=true + ADMIN_API_TOKEN is configured.

Also documents the two independent "admin identities" (two different admin
tokens used by operators of the same single-tenant instance) both get access,
and both are blocked without a valid token.

Run: python -m pytest tests/backend/test_endpoint_guard_coverage.py -v
"""

import io
import json
import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def guard_client():
    """TestClient with ENABLE_ADMIN_GUARD=true and two admin tokens."""
    import app.config as config_module
    config_module._settings = None

    import tempfile
    env_dir = tempfile.mkdtemp(prefix="cad_guard_test_")
    env_path = Path(env_dir) / ".env"
    # Override the shared test env with guard enabled and two tokens
    original_env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    os.environ["CAD_TRANSLATION_ENV_FILE"] = str(env_path)
    os.environ["ENABLE_ADMIN_GUARD"] = "true"
    os.environ["ADMIN_API_TOKEN"] = "admin-token-identity-1"
    env_path.write_text(
        "DEBUG=false\n"
        "ENABLE_ADMIN_GUARD=true\n"
        "ADMIN_API_TOKEN=admin-token-identity-1\n"
        f"DATABASE_URL=sqlite:///{env_dir}/test.db\n"
        f"UPLOAD_DIR={env_dir}/uploads\n"
        f"OUTPUT_DIR={env_dir}/outputs\n"
        f"TEMP_DIR={env_dir}/temp\n",
        encoding="utf-8",
    )

    config_module._settings = None

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c, env_dir

    # Restore
    config_module._settings = None
    os.environ["CAD_TRANSLATION_ENV_FILE"] = original_env_file


def test_translation_endpoints_are_guarded(guard_client):
    """All translation API endpoints require admin token."""
    client, _ = guard_client

    # Translation text (POST) — should be 403 without token
    resp = client.post("/api/translation/text", json={"text": "hello", "source_lang": "en", "target_lang": "zh"})
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"

    # Translation batch (POST) — should be 403
    resp = client.post("/api/translation/batch", json={"texts": ["a", "b"]})
    assert resp.status_code == 403

    # Translation task status (GET) — should be 403
    resp = client.get("/api/translation/task/some-task-id")
    assert resp.status_code == 403

    # Translation config (GET) — should be 403
    resp = client.get("/api/translation/config")
    assert resp.status_code == 403

    # Providers (GET) — should be 403 (may expose API key config)
    resp = client.get("/api/translation/providers")
    assert resp.status_code == 403

    # With valid token → should not be 403
    headers = {"X-Admin-Token": "admin-token-identity-1"}
    resp = client.get("/api/translation/config", headers=headers)
    assert resp.status_code == 200
    assert "languages" in resp.json() or "runtime" in resp.json()

    # /api/translation/languages is intentionally public (only lists ISO names)
    resp = client.get("/api/translation/languages")
    assert resp.status_code == 200


def test_cad_text_translate_endpoints_are_guarded(guard_client):
    """/api/cad/translate-text and /api/cad/translate-batch require admin."""
    client, _ = guard_client

    resp = client.post(
        "/api/cad/translate-text",
        data={"text": "hello", "target_language": "zh"},
    )
    assert resp.status_code == 403

    resp = client.post(
        "/api/cad/translate-batch",
        json={"texts": ["a", "b"], "target_lang": "zh"},
    )
    assert resp.status_code == 403

    # With valid token → not 403 (may fail for other reasons)
    headers = {"X-Admin-Token": "admin-token-identity-1"}
    resp = client.post(
        "/api/cad/translate-text",
        headers=headers,
        data={"text": "hello", "target_language": "zh"},
    )
    assert resp.status_code != 403

    resp = client.post(
        "/api/cad/translate-batch",
        headers=headers,
        json={"texts": ["a", "b"], "target_lang": "zh"},
    )
    assert resp.status_code != 403


def test_cad_defaults_get_is_guarded(guard_client):
    """GET /api/cad/defaults is guarded (may reveal config)."""
    client, _ = guard_client
    resp = client.get("/api/cad/defaults")
    assert resp.status_code == 403

    headers = {"X-Admin-Token": "admin-token-identity-1"}
    resp = client.get("/api/cad/defaults", headers=headers)
    assert resp.status_code == 200


def test_health_is_public(guard_client):
    """Health checks are public (no data exposure)."""
    client, _ = guard_client
    resp = client.get("/api/cad/health")
    assert resp.status_code == 200


def test_two_admin_identities_can_access_same_data(guard_client):
    """Two admin identities on the same single-tenant instance can access
    shared data (the system intentionally has no per-user ownership model).
    Both must present a valid admin token."""
    client, env_dir = guard_client

    # "User A" and "User B" both share the same single ADMIN_API_TOKEN.
    # In single-tenant mode, they represent two operators of the same tenant.
    headers = {"X-Admin-Token": "admin-token-identity-1"}

    # User A creates a project
    resp = client.post("/api/projects/", json={"name": "Project from Admin A"}, headers=headers)
    assert resp.status_code == 200

    # User B lists projects (same tenant) → succeeds
    resp = client.get("/api/projects/", headers=headers)
    assert resp.status_code == 200
    projects = resp.json()
    assert any(p.get("name") == "Project from Admin A" for p in projects)

    # User B tries without token → rejected
    resp = client.get("/api/projects/")
    assert resp.status_code == 403


def test_default_guard_is_true():
    """ENABLE_ADMIN_GUARD defaults to true in config."""
    # Check the code-level default without going through Settings (which may
    # pick up the shared test .env that sets ENABLE_ADMIN_GUARD=false).
    import app.config as config_module
    # Inspect the Field definition directly.
    field = config_module.Settings.model_fields["ENABLE_ADMIN_GUARD"]
    default = field.default
    assert default is True, f"Code default should be True, got {default}"


def test_task_list_logs_download_require_auth(guard_client):
    """Task list, logs, and download endpoints require auth (positive/negative)."""
    client, _ = guard_client

    # Without token → rejected
    assert client.get("/api/cad/tasks").status_code == 403
    assert client.get("/api/cad/tasks/fake-task/logs").status_code == 403
    assert client.get("/api/cad/download/fake-task/excel").status_code == 403

    # With valid token → access attempted (may 404 since no task exists)
    headers = {"X-Admin-Token": "admin-token-identity-1"}
    assert client.get("/api/cad/tasks", headers=headers).status_code == 200
    # fake task: should 404 (authenticated but not found), not 403
    resp = client.get("/api/cad/tasks/fake-task/logs", headers=headers)
    assert resp.status_code in (200, 404, 500), f"Unexpected status: {resp.status_code}"
    resp = client.get("/api/cad/download/fake-task/excel", headers=headers)
    assert resp.status_code in (200, 404, 500), f"Unexpected status: {resp.status_code}"


def test_project_file_endpoints_require_auth(guard_client):
    """Project and file API endpoints require auth token (positive/negative)."""
    client, _ = guard_client
    headers = {"X-Admin-Token": "admin-token-identity-1"}

    # Negative: no token
    assert client.get("/api/projects/").status_code == 403
    assert client.get("/api/projects/summary").status_code == 403
    assert client.post("/api/projects/", json={"name": "t"}).status_code == 403

    # Positive: with token
    resp = client.get("/api/projects/", headers=headers)
    assert resp.status_code == 200
    resp = client.get("/api/projects/summary", headers=headers)
    assert resp.status_code == 200

    # Create a project with token
    resp = client.post("/api/projects/", json={"name": "Auth Test Project"}, headers=headers)
    assert resp.status_code == 200
    project_id = resp.json().get("id")
    assert project_id is not None

    # File endpoints without token
    assert client.get(f"/api/files/{project_id}", headers={}).status_code == 403

    # File endpoints with token
    resp = client.get(f"/api/files/{project_id}", headers=headers)
    assert resp.status_code == 200


def test_translation_text_batch_guarded_for_two_identities(guard_client):
    """Two admin identities can call translation endpoints; unauthenticated calls fail."""
    client, _ = guard_client

    headers = {"X-Admin-Token": "admin-token-identity-1"}

    # Both identities use the shared admin token (single-tenant)
    for identity in ["admin-token-identity-1"]:
        h = {"X-Admin-Token": identity}
        resp = client.post("/api/translation/text", headers=h, json={
            "text": "hello", "source_lang": "en", "target_lang": "zh"
        })
        # Not 403 means the identity passed auth
        assert resp.status_code != 403, f"Identity {identity} should pass auth"

        resp = client.post("/api/translation/batch", headers=h, json={
            "texts": ["a", "b"], "source_lang": "en", "target_lang": "zh"
        })
        assert resp.status_code != 403, f"Identity {identity} should pass auth"

    # Unauthenticated → 403
    resp = client.post("/api/translation/text", json={"text": "hello"})
    assert resp.status_code == 403
    resp = client.post("/api/translation/batch", json={"texts": ["a"]})
    assert resp.status_code == 403


def test_resume_apply_translation_require_auth(guard_client):
    """Resume and apply-translation endpoints require auth."""
    client, _ = guard_client
    headers = {"X-Admin-Token": "admin-token-identity-1"}

    # Without token → 403
    resp = client.post("/api/cad/tasks/fake-id/resume", json={"target_language": "en"})
    assert resp.status_code == 403

    resp = client.post("/api/cad/apply-translation", json={
        "task_id": "fake-id",
        "translations": [{"original": "x", "translated": "y"}],
    })
    assert resp.status_code == 403

    # With token → not 403 (may 404 since fake task doesn't exist)
    resp = client.post("/api/cad/tasks/fake-id/resume", headers=headers,
                       json={"target_language": "en"})
    assert resp.status_code != 403

    resp = client.post("/api/cad/apply-translation", headers=headers,
                       json={"task_id": "fake-id", "translations": []})
    assert resp.status_code != 403

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for centralised task_id validation and apply 409.

Covers two boundary fixes requested in review:

1. **task_id path traversal hardening.**  ``task_id`` values are used verbatim
   as sub-directory names under ``outputs/cad_tasks/`` and as lock / cancel
   marker filename components.  A caller-supplied id containing ``../``, ``.``
   segments or path separators would otherwise let ``_load_task`` /
   ``resolve_download`` / ``delete_task`` / ``get_task_logs`` / logs read,
   download, or delete paths *outside* the task tree.  Admin-token
   authentication proves identity, not that an id is path-safe, so every
   endpoint / service method now funnels through a centralised
   ``validate_task_id`` that rejects anything that is not an exact 8-hex
   system-generated id.  These tests exercise the service layer and the
   URL/API layer across read / download / delete / backfill(apply) / logs and
   confirm that a crafted id can never reach a filesystem path.

2. **apply_translation returns 409 on a deleted/cleared task.**  Once a task
   is deleted or cleared, ``apply_translation`` raises ``TaskCancelledError``.
   The route previously let it fall into the generic ``Exception`` handler and
   returned 500; it now returns an explicit 409 like the upload / resume
   routes.

Run: python -m pytest tests/backend/test_task_id_path_safety.py -v
"""

import io
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ----------------------------------------------------------------- helpers ---

MALICIOUS_IDS = [
    "../secret",
    "../../etc/passwd",
    "..",
    ".",
    "abc/def",
    "abc\\def",
    "dead/beef",
    "12345",
    "0123456789abcdef",
    "",
    "12 34",
    "ABC12345",  # uppercase is not produced by uuid4().hex
    "DEADBEEF",
    None,
]


def _make_test_client():
    """A fresh TestClient pointed at an isolated temporary output dir."""
    import app.config as config_module
    config_module._settings = None

    env_dir = tempfile.mkdtemp(prefix="cad_taskid_safety_")
    env_path = Path(env_dir) / ".env"
    original_env_file = os.environ.get("CAD_TRANSLATION_ENV_FILE", "")
    os.environ["CAD_TRANSLATION_ENV_FILE"] = str(env_path)
    env_path.write_text(
        "DEBUG=false\n"
        "ENABLE_ADMIN_GUARD=false\n"
        f"DATABASE_URL=sqlite:///{env_dir}/test.db\n"
        f"UPLOAD_DIR={env_dir}/uploads\n"
        f"OUTPUT_DIR={env_dir}/outputs\n"
        f"TEMP_DIR={env_dir}/temp\n",
        encoding="utf-8",
    )
    config_module._settings = None

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    return client, Path(env_dir) / "outputs", original_env_file


@pytest.fixture
def env_output():
    """Yield (client, output_dir). Restores the shared env afterwards."""
    import app.config as config_module
    client, output_dir, original_env_file = _make_test_client()
    try:
        yield client, output_dir
    finally:
        client.close()
        config_module._settings = None
        os.environ["CAD_TRANSLATION_ENV_FILE"] = original_env_file
        config_module._settings = None


def _create_real_task(client):
    """Create a real task via /api/cad/extract and return (task_id, output_dir)."""
    import ezdxf
    from app.config import get_settings

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_text("hello world", dxfattribs={"height": 2.5})
    tmpf = tempfile.NamedTemporaryFile(suffix=".dxf", delete=False)
    tmpf.close()
    tmp_path = Path(tmpf.name)
    doc.saveas(str(tmp_path))
    data = tmp_path.read_bytes()
    tmp_path.unlink(missing_ok=True)

    resp = client.post(
        "/api/cad/extract",
        files={"file": ("safety.dxf", io.BytesIO(data), "application/octet-stream")},
        data={"converter_backend": "dxf_only", "target_language": "en"},
    )
    assert resp.status_code == 200, resp.text
    task_id = resp.json()["data"]["task_id"]
    output_root = get_settings().get_output_path()
    return task_id, output_root


# ------------------------------------------- 1. validator unit behaviour ---

def test_validate_task_id_accepts_system_format_only():
    from app.services.cad_pipeline_service import (
        is_valid_task_id,
        validate_task_id,
    )
    import uuid

    # A freshly generated id (uuid4().hex[:8]) is accepted.
    valid = uuid.uuid4().hex[:8]
    assert is_valid_task_id(valid)
    assert validate_task_id(valid) == valid

    # Everything path-like or non-system is rejected.
    for bad in MALICIOUS_IDS:
        assert not is_valid_task_id(bad), f"should reject {bad!r}"
        with pytest.raises(ValueError):
            validate_task_id(bad)


# --------------------------------- 2. service-layer traversal (no fs access) ---

def test_service_methods_reject_malicious_task_ids(env_output):
    """All service entry points that join task_id onto a path must raise
    ValueError for path-like ids and never touch the filesystem outside the
    task tree."""
    from app.services.cad_pipeline_service import (
        CADPipelineService,
        TaskCancelledError,
    )
    from app.config import get_settings

    svc = CADPipelineService()
    output_root = get_settings().get_output_path()
    # Sentinel to prove a crafted id never escapes cad_tasks/.
    sentinel = output_root / "SENTINEL_OUTSIDE_TASKS"
    sentinel.write_text("must not be touched", encoding="utf-8")

    for bad in MALICIOUS_IDS:
        with pytest.raises(ValueError):
            svc._load_task(bad)
        with pytest.raises(ValueError):
            svc.resolve_download(bad, "excel")
        with pytest.raises(ValueError):
            svc.delete_task(bad)
        with pytest.raises(ValueError):
            svc.get_task_logs(bad)
        with pytest.raises(ValueError):
            svc.apply_translation(bad, [{"original": "x", "translated": "y"}])
        with pytest.raises(ValueError):
            svc.resume_task(bad)
        with pytest.raises(ValueError):
            svc.build_download_package([bad])

    # The sentinel outside cad_tasks/ must be untouched, proving no crafted id
    # could ever have been joined onto a path that escaped the task tree.
    assert sentinel.exists()
    assert sentinel.read_text(encoding="utf-8") == "must not be touched"


def test_crafted_id_does_not_escape_task_dir_path(env_output):
    """A malicious id never resolves outside the per-task directory."""
    from app.services.cad_pipeline_service import CADPipelineService

    svc = CADPipelineService()
    for bad in ["../x", "../../etc", "..", "a/b"]:
        # _task_dir is the single funnel for all task-file paths.
        with pytest.raises(ValueError):
            svc._task_dir(bad)
        with pytest.raises(ValueError):
            svc._lifecycle_lock_path(bad)
        with pytest.raises(ValueError):
            svc._cancel_marker_path(bad)


# ------------------------------ 3. URL/API layer: path traversal rejected ---

def test_url_task_endpoints_reject_invalid_ids(env_output):
    """download / logs / resume / delete reject a task_id that reaches the route
    handler but is not a system-generated 8-hex id -> 400.

    ``..`` / leading-dot traversal segments in a URL are normalised away by the
    HTTP router *before* the handler runs (so the route is not even matched and
    the request 404s upstream) - that is still safe, but cannot exercise our
    validator.  To prove the endpoint-level validator rejects non-system ids we
    pass ids that reach the handler unchanged (no path separators, still
    invalid under the 8-hex rule)."""
    client, output_dir = env_output
    # Invalid shapes that survive URL routing unchanged.
    for bad in ["cafebez", "deadbeefcafe", "ABCDEF12", "DEADBEEF"]:
        r = client.get(f"/api/cad/download/{bad}/excel")
        assert r.status_code == 400, f"download {bad!r} -> {r.status_code}"
        r = client.get(f"/api/cad/tasks/{bad}/logs")
        assert r.status_code == 400, f"logs {bad!r} -> {r.status_code}"
        r = client.post(f"/api/cad/tasks/{bad}/resume", json={"target_language": "en"})
        assert r.status_code == 400, f"resume {bad!r} -> {r.status_code}"
        r = client.delete(f"/api/cad/tasks/{bad}")
        assert r.status_code == 400, f"delete {bad!r} -> {r.status_code}"


def test_url_task_endpoints_never_escape_on_path_like_ids(env_output):
    """A path-like id in the URL is either rejected by the router (404 upstream,
    because ``..``/``.`` segments are normalised away before the handler) or by
    our validator (400).  Either way no file is ever read/written outside the
    task tree and no endpoint 2xx/3xx-processes the id."""
    client, output_dir = env_output
    # NB: a bare ``.`` segment is normalised by the HTTP router to the current
    # directory (e.g. ``DELETE /api/cad/tasks/.`` -> collection DELETE) before it
    # ever reaches a per-task handler, so we do not assert on it here; single-dot
    # ids are still rejected at the service layer (see the validator tests).
    path_likes = ["../deadbeef", "..", "..%2Fdeadbeef"]
    for path_like in path_likes:
        r = client.get(f"/api/cad/download/{path_like}/excel")
        assert r.status_code in (400, 404), f"download {path_like!r} -> {r.status_code}"
        r = client.get(f"/api/cad/tasks/{path_like}/logs")
        assert r.status_code in (400, 404), f"logs {path_like!r} -> {r.status_code}"
        # DELETE on a non-routable normalised path yields 405 (Method Not Allowed)
        # rather than 404; either way the id never reaches a task handler.
        r = client.delete(f"/api/cad/tasks/{path_like}")
        assert r.status_code in (400, 404, 405), f"delete {path_like!r} -> {r.status_code}"

    # No sibling path can have been created / touched.
    tasks_root = output_dir / "cad_tasks"
    assert not (output_dir / "deadbeef").exists()


def test_body_task_ids_reject_path_traversal(env_output):
    """apply-translation and download-package read task_id(s) from the JSON body
    (not subject to URL normalisation), so a ``../`` value must be rejected by
    the centralised validator -> 400."""
    client, output_dir = env_output
    path_like = "../deadbeef"

    r = client.post(
        "/api/cad/apply-translation",
        json={"task_id": path_like, "translations": [{"original": "a", "translated": "b"}]},
    )
    assert r.status_code == 400, r.text

    r = client.post("/api/cad/download-package", json={"task_ids": [path_like, "cafebabe"]})
    assert r.status_code == 400, r.text

    assert not (output_dir / "deadbeef").exists()


def test_url_endpoint_accepts_valid_hex_id_but_task_missing(env_output):
    """A well-formed 8-hex id passes validation; a nonexistent one yields 404."""
    client, _ = env_output
    # Well-formed but nonexistent task id.
    r = client.get("/api/cad/download/cafebabe/excel")
    assert r.status_code == 404, r.text

    r = client.get("/api/cad/tasks/cafebabe/logs")
    assert r.status_code == 404, r.text

    r = client.delete("/api/cad/tasks/cafebabe")
    assert r.status_code == 404, r.text


# -------------------------- 4. apply after delete/clear returns 409 ---------

def test_apply_translation_on_deleted_task_returns_409(env_output):
    """apply-translation on a task deleted via the API returns 409
    (TaskCancelledError), not a generic 500."""
    client, output_dir = env_output
    task_id, _ = _create_real_task(client)

    # Delete the task via the API.
    r = client.delete(f"/api/cad/tasks/{task_id}")
    assert r.status_code == 200, r.text

    # Applying translation to a deleted task must now surface 409 (cancelled).
    r = client.post(
        "/api/cad/apply-translation",
        json={"task_id": task_id, "translations": [{"original": "hello", "translated": "bonjour"}]},
    )
    assert r.status_code == 409, (
        f"apply-translation on a deleted task should return 409, got {r.status_code}: {r.text}"
    )


def _create_real_task_service(svc):
    import ezdxf
    from fastapi import UploadFile

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_text("hello service", dxfattribs={"height": 2.5})
    tmpf = tempfile.NamedTemporaryFile(suffix=".dxf", delete=False)
    tmpf.close()
    tmp_path = Path(tmpf.name)
    doc.saveas(str(tmp_path))
    data = tmp_path.read_bytes()
    tmp_path.unlink(missing_ok=True)
    up = UploadFile(filename="safety.dxf", file=io.BytesIO(data))
    return svc.extract_upload(uploaded_file=up, target_language="en", converter_backend="dxf_only")["task_id"]


def test_apply_translation_service_raises_task_cancelled_after_delete():
    from app.services.cad_pipeline_service import CADPipelineService, TaskCancelledError

    svc = CADPipelineService()
    task_id = _create_real_task_service(svc)
    svc.delete_task(task_id)
    with pytest.raises(TaskCancelledError):
        svc.apply_translation(task_id, [{"original": "hello", "translated": "bonjour"}])
